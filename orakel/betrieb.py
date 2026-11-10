"""Phase 8: Dauerbetrieb mit Zeitplan, Backoff und Ressourcenlimits.

Der Betrieb ist bewusst kein zweiter Scheduler neben dem bestehenden Takt. Er
ersetzt die direkte Abfolge in ``scheduler.takt_schritt`` durch einen Plan:

* Jeder Job hat ein Intervall und einen persistenten nächsten Versuch.
* Fehler führen zu exponentiellem Backoff; der Zustand überlebt Neustarts.
* Schreibintensive Jobs werden bei knapper Datenbank, knappem Speicher oder
  zu hohem Prozess-RSS übersprungen.
* Jeder Lauf landet kompakt in ``betrieb_laeufe`` und ist über API/CLI lesbar.

Es werden keine zusätzlichen Missionen, Artikel oder Kennzahlen erzeugt.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .db import Facts
from .intel import IntelNetz
from .knowledge import Vault
from .nexus.missionen import Missionen
from .paper import tick
from .spider import Spider

STATUS_KEY = "betrieb_status"
STATUS_VERSION = 1


def _int(wert: object, standard: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(wert))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return standard


def _float(wert: object, standard: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(wert))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return standard


def _zeit(text: object) -> datetime | None:
    try:
        wert = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert


def _iso(wert: datetime) -> str:
    return wert.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _rss_mb() -> float | None:
    """Liest den Spitzen-RSS ohne zusätzliche Abhängigkeit."""
    try:
        import resource

        rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux meldet KiB, macOS Bytes.
        return round(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024, 1)
    except Exception:
        return None


def datenbank_mb(pfad: str | Path) -> float:
    """Zählt DB plus WAL/SHM; eine wachsende WAL ist Teil des Verbrauchs."""
    basis = Path(pfad)
    bytes_gesamt = 0
    for datei in (basis, Path(f"{basis}-wal"), Path(f"{basis}-shm")):
        try:
            bytes_gesamt += datei.stat().st_size
        except OSError:
            pass
    return round(bytes_gesamt / (1024 * 1024), 2)


def ressourcen_snapshot(db: Facts) -> dict[str, Any]:
    db_mb = datenbank_mb(db.pfad)
    rss_mb = _rss_mb()
    frei_mb: float | None = None
    gesamt_mb: float | None = None
    try:
        nutzung = shutil.disk_usage(db.pfad.parent)
        frei_mb = round(nutzung.free / (1024 * 1024), 1)
        gesamt_mb = round(nutzung.total / (1024 * 1024), 1)
    except OSError:
        pass
    return {
        "db_mb": db_mb,
        "rss_mb": rss_mb,
        "freier_speicher_mb": frei_mb,
        "speicher_gesamt_mb": gesamt_mb,
        "prozess_pid": os.getpid(),
    }


@dataclass(frozen=True, slots=True)
class BetriebsGrenzen:
    """Harte Betriebsgrenzen. 0 bedeutet: diese Grenze ist absichtlich zu."""

    max_db_mb: float
    max_rss_mb: float
    min_freier_speicher_mb: float
    max_takt_sekunden: float
    max_laeufe: int

    @classmethod
    def aus_config(cls, cfg: Config) -> "BetriebsGrenzen":
        b = cfg.abschnitt("betrieb")
        return cls(
            max_db_mb=_float(b.get("max_db_mb"), 512.0),
            max_rss_mb=_float(b.get("max_rss_mb"), 768.0),
            min_freier_speicher_mb=_float(b.get("min_freier_speicher_mb"), 256.0),
            max_takt_sekunden=_float(b.get("max_takt_sekunden"), 240.0),
            max_laeufe=_int(b.get("max_laeufe"), 1000, 100),
        )

    def als_dict(self) -> dict[str, Any]:
        return {
            "max_db_mb": self.max_db_mb,
            "max_rss_mb": self.max_rss_mb,
            "min_freier_speicher_mb": self.min_freier_speicher_mb,
            "max_takt_sekunden": self.max_takt_sekunden,
            "max_laeufe": self.max_laeufe,
        }


@dataclass(frozen=True, slots=True)
class Job:
    """Ein geplanter Job. Die Funktion wird ausschließlich vom Takt gerufen."""

    name: str
    titel: str
    funktion: Callable[[], Any]
    intervall_sekunden: int
    backoff_max_sekunden: int
    ressourcen_intensiv: bool = False


def _job_fehler_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:500]}"


def _kompakte_details(wert: object) -> dict[str, Any]:
    """Nur skalare Kennzahlen ins Jobprotokoll, keine Artikeltexte."""
    if not isinstance(wert, dict):
        return {}
    erlaubt = {
        "quellen", "gelesen", "neu", "notizen", "analysiert", "fehler",
        "ausgefuehrt", "erledigt", "retries", "dead_letter", "leases",
        "weiterleitungen", "auftraege", "artikel", "kennung", "dauer_sekunden",
        "tasks_erzeugt", "tasks_verarbeitet", "profile", "tag",
    }
    out: dict[str, Any] = {}
    for schluessel, wert2 in wert.items():
        if schluessel not in erlaubt:
            continue
        if isinstance(wert2, (str, int, float, bool)) or wert2 is None:
            out[schluessel] = (wert2[:240] if isinstance(wert2, str) else wert2)
        elif isinstance(wert2, (list, tuple)):
            out[schluessel] = len(wert2)
    return out


class Betrieb:
    """Führt fällige Jobs aus und hält ihren Zustand in SQLite."""

    def __init__(
        self,
        cfg: Config,
        db: Facts,
        *,
        jetzt_funktion: Callable[[], datetime] | None = None,
        jobs: dict[str, Callable[[], Any]] | None = None,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self._jetzt_funktion = jetzt_funktion or (lambda: datetime.now(timezone.utc))
        self.grenzen = BetriebsGrenzen.aus_config(cfg)
        self.betrieb_cfg = cfg.abschnitt("betrieb")
        self.takt_sekunden = max(5, _int(cfg.abschnitt("paper").get("takt_sekunden"),
                                        60, 5))
        self._spider_ergebnis: dict[str, Any] | None = None
        self._status = self._status_laden()
        self.jobs = self._job_liste(jobs)

    # ---------- Zustand ----------
    def _jetzt(self) -> datetime:
        wert = self._jetzt_funktion()
        if wert.tzinfo is None:
            wert = wert.replace(tzinfo=timezone.utc)
        return wert.astimezone(timezone.utc).replace(microsecond=0)

    def _status_laden(self) -> dict[str, Any]:
        roh = self.db.zustand(STATUS_KEY)
        if not isinstance(roh, dict):
            roh = {}
        roh.setdefault("version", STATUS_VERSION)
        if not isinstance(roh.get("jobs"), dict):
            roh["jobs"] = {}
        roh.setdefault("letzter_takt", None)
        roh.setdefault("letzter_takt_status", None)
        roh.setdefault("letzter_takt_dauer_ms", 0)
        roh.setdefault("takt_nummer", 0)
        roh.setdefault("gestartet", None)
        return roh

    def _job_status(self, name: str) -> dict[str, Any]:
        jobs = self._status.setdefault("jobs", {})
        eintrag = jobs.get(name)
        if not isinstance(eintrag, dict):
            eintrag = {}
            jobs[name] = eintrag
        for schluessel, standard in (
            ("letzter_start", None), ("letzter_erfolg", None),
            ("letzter_fehler", None), ("fehlschluesse", 0),
            ("naechster_versuch", None), ("backoff_sekunden", 0),
            ("letzter_status", None), ("uebersprungen", None),
            ("uebersprungen_grund", ""),
        ):
            eintrag.setdefault(schluessel, standard)
        return eintrag

    def _status_speichern(self) -> None:
        self._status["version"] = STATUS_VERSION
        self._status["aktualisiert"] = _iso(self._jetzt())
        self.db.zustand_setzen(STATUS_KEY, self._status)

    # ---------- Plan ----------
    def _job_liste(self, jobs: dict[str, Callable[[], Any]] | None) -> list[Job]:
        from .scheduler import konferenz_nachholen

        b = self.betrieb_cfg
        missionen_max = _int(b.get("max_missionen_pro_takt"), 5, 1)
        spider_aktiv = bool(self.cfg.abschnitt("spider").get("aktiv", True))
        unternehmen_aktiv = bool(
            self.cfg.abschnitt("unternehmen").get("aktiv", False))

        def spider_lauf() -> dict[str, Any]:
            ergebnis = Spider(
                self.cfg, self.db, Vault(self.cfg.vault_ordner)).lauf()
            self._spider_ergebnis = ergebnis
            self.db.zustand_setzen("spider_letzter_lauf", ergebnis)
            # Ein Lauf, bei dem alle Quellen scheitern, ist kein Erfolg.
            if (int(ergebnis.get("quellen") or 0) > 0
                    and int(ergebnis.get("gelesen") or 0) == 0
                    and ergebnis.get("fehler")):
                raise RuntimeError(
                    f"Spider: {len(ergebnis['fehler'])} Quelle(n) fehlgeschlagen")
            return ergebnis

        def intel_lauf() -> dict[str, Any]:
            netz = IntelNetz(self.cfg, self.db, Vault(self.cfg.vault_ordner))
            ids = (self._spider_ergebnis or {}).get("neue_ids") or []
            return {**netz.verarbeite(ids), **netz.lernschleife()}

        def missionen_lauf() -> dict[str, Any]:
            return Missionen(self.db, vault=Vault(self.cfg.vault_ordner)
                             ).weiterarbeiten(max_tasks=missionen_max)

        def unternehmen_lauf() -> dict[str, Any]:
            from .company.runtime import CompanyRuntime

            return CompanyRuntime(self.cfg, self.db).run()

        plan = [
            Job("paper", "Paper-Takt", lambda: tick(self.cfg, self.db),
                0, _int(b.get("backoff_max_sekunden"), 3600, 60)),
            Job("konferenz", "Mitternachtskonferenz",
                lambda: konferenz_nachholen(self.cfg, self.db),
                0, _int(b.get("backoff_max_sekunden"), 3600, 60)),
        ]
        if spider_aktiv:
            plan.append(Job(
                "spider", "Quellen abrufen",
                spider_lauf,
                _int(b.get("spider_intervall_minuten"), 360, 1) * 60,
                _int(b.get("spider_backoff_max_sekunden"), 21600, 60),
                ressourcen_intensiv=True,
            ))
        plan.extend([
            Job("intel", "Intelligence-Netz",
                intel_lauf, 0, _int(b.get("backoff_max_sekunden"), 3600, 60)),
            Job("missionen", "Missionen-Queue",
                missionen_lauf, 0, _int(b.get("backoff_max_sekunden"), 3600, 60)),
        ])
        if unternehmen_aktiv:
            plan.append(Job(
                "unternehmen", "Company-Schicht",
                unternehmen_lauf,
                _int(b.get("unternehmen_intervall_minuten"), 60, 1) * 60,
                _int(b.get("backoff_max_sekunden"), 3600, 60),
                ressourcen_intensiv=True,
            ))
        if jobs is None:
            return plan
        # Tests und kontrollierte Läufe können einzelne Funktionen ersetzen.
        nach_name = {job.name: job for job in plan}
        ersetzt: list[Job] = []
        for name, funktion in jobs.items():
            if name not in nach_name:
                raise ValueError(f"Unbekannter Betriebsjob: {name}")
            ersetzt.append(replace(nach_name[name], funktion=funktion))
        return ersetzt

    # ---------- Ausführung ----------
    def _faellig(self, job: Job, status: dict[str, Any], jetzt: datetime) -> bool:
        naechster = _zeit(status.get("naechster_versuch"))
        return naechster is None or jetzt >= naechster

    def _backoff(self, status: dict[str, Any], maximum: int) -> int:
        basis = _int(self.betrieb_cfg.get("backoff_basis_sekunden"), 60, 1)
        versuche = max(1, int(status.get("fehlschluesse") or 0))
        return min(int(maximum), basis * (2 ** min(versuche - 1, 16)))

    def _budget_grund(self, job: Job, snapshot: dict[str, Any],
                      start: float | None = None) -> str:
        if start is not None and self.grenzen.max_takt_sekunden > 0:
            if time.monotonic() - start >= self.grenzen.max_takt_sekunden:
                return (f"Taktbudget von {self.grenzen.max_takt_sekunden:g} s "
                        "überschritten")
        if not job.ressourcen_intensiv:
            return ""
        if self.grenzen.max_db_mb > 0 and snapshot["db_mb"] >= self.grenzen.max_db_mb:
            return (f"Datenbank {snapshot['db_mb']:.1f} MB ≥ "
                    f"{self.grenzen.max_db_mb:g} MB")
        if (self.grenzen.max_rss_mb > 0 and snapshot.get("rss_mb") is not None
                and snapshot["rss_mb"] >= self.grenzen.max_rss_mb):
            return (f"Prozess-RSS {snapshot['rss_mb']:.1f} MB ≥ "
                    f"{self.grenzen.max_rss_mb:g} MB")
        frei = snapshot.get("freier_speicher_mb")
        if (self.grenzen.min_freier_speicher_mb > 0 and frei is not None
                and frei <= self.grenzen.min_freier_speicher_mb):
            return (f"Freier Speicher {frei:.1f} MB ≤ "
                    f"{self.grenzen.min_freier_speicher_mb:g} MB")
        return ""

    def _pause_nach_grenze(self) -> int:
        return _int(self.betrieb_cfg.get("grenze_pause_sekunden"), 300, 30)

    def _protokoll(self, job: str, status: str, dauer_ms: int = 0,
                   fehler: str = "", details: dict[str, Any] | None = None) -> None:
        try:
            self.db.betrieb_lauf_speichern(
                job, status, dauer_ms=dauer_ms, fehler=fehler,
                details=_kompakte_details(details or {}),
            )
        except Exception:
            # Das Protokoll darf den Betrieb nie anhalten.
            pass

    def takt(self, erzwungen: set[str] | None = None) -> dict[str, Any]:
        """Führt alle fälligen Jobs aus. Rückgabe behält die alten Schlüssel."""
        erzwungen = set(erzwungen or ())
        jetzt = self._jetzt()
        self._status["gestartet"] = self._status.get("gestartet") or _iso(jetzt)
        self._status["takt_nummer"] = int(self._status.get("takt_nummer") or 0) + 1
        self._spider_ergebnis = None
        budget_start = time.monotonic()
        snapshot = ressourcen_snapshot(self.db)
        ergebnis: dict[str, Any] = {
            "betrieb": {
                "takt": _iso(jetzt),
                "takt_nummer": self._status["takt_nummer"],
                "jobs": {},
                "uebersprungen": {},
            }
        }
        fehler_im_takt = False

        for job in self.jobs:
            status = self._job_status(job.name)
            if not self._faellig(job, status, jetzt) and job.name not in erzwungen:
                continue

            grund = self._budget_grund(job, snapshot, budget_start)
            if grund:
                status["letzter_status"] = "uebersprungen"
                status["uebersprungen"] = _iso(jetzt)
                status["uebersprungen_grund"] = grund
                status["naechster_versuch"] = _iso(
                    jetzt + timedelta(seconds=self._pause_nach_grenze()))
                ergebnis[job.name] = {"uebersprungen": grund}
                ergebnis["betrieb"]["uebersprungen"][job.name] = grund
                ergebnis["betrieb"]["jobs"][job.name] = "uebersprungen"
                self._protokoll(job.name, "uebersprungen", 0, grund)
                self._status_speichern()
                continue

            status["letzter_start"] = _iso(jetzt)
            status["uebersprungen"] = None
            status["uebersprungen_grund"] = ""
            beginn = time.monotonic()
            try:
                wert = job.funktion()
                dauer = int((time.monotonic() - beginn) * 1000)
                status["letzter_erfolg"] = _iso(jetzt)
                status["letzter_status"] = "ok"
                status["fehlschluesse"] = 0
                status["backoff_sekunden"] = 0
                status["naechster_versuch"] = _iso(
                    jetzt + timedelta(seconds=job.intervall_sekunden))
                ergebnis[job.name] = wert
                ergebnis["betrieb"]["jobs"][job.name] = "ok"
                self._protokoll(job.name, "ok", dauer, "", _kompakte_details(wert))
            except Exception as exc:
                dauer = int((time.monotonic() - beginn) * 1000)
                fehler_im_takt = True
                status["letzter_status"] = "fehler"
                status["fehlschluesse"] = int(status.get("fehlschluesse") or 0) + 1
                status["backoff_sekunden"] = self._backoff(
                    status, job.backoff_max_sekunden)
                status["naechster_versuch"] = _iso(
                    jetzt + timedelta(seconds=status["backoff_sekunden"]))
                status["letzter_fehler"] = {
                    "zeit": _iso(jetzt),
                    "text": _job_fehler_text(exc),
                    "art": type(exc).__name__,
                }
                ergebnis[job.name] = {"fehler": _job_fehler_text(exc)}
                ergebnis["betrieb"]["jobs"][job.name] = "fehler"
                self._protokoll(job.name, "fehler", dauer, _job_fehler_text(exc))
                try:
                    self.db.ereignis(
                        "fehler", "Betrieb",
                        f"{job.titel}: {_job_fehler_text(exc)}; nächster Versuch "
                        f"in {status['backoff_sekunden']} s")
                except Exception:
                    pass
            finally:
                self._status_speichern()

        self._status["letzter_takt"] = _iso(jetzt)
        self._status["letzter_takt_status"] = "fehler" if fehler_im_takt else "ok"
        self._status["letzter_takt_dauer_ms"] = int(
            (time.monotonic() - budget_start) * 1000)
        self._status_speichern()
        try:
            self.db.betrieb_laeufe_trim(self.grenzen.max_laeufe)
        except Exception:
            pass
        ergebnis["betrieb"]["status"] = self._status["letzter_takt_status"]
        ergebnis["betrieb"]["dauer_ms"] = self._status["letzter_takt_dauer_ms"]
        return ergebnis

    # ---------- Monitoring ----------
    def _takt_aktiv(self, jetzt: datetime) -> bool:
        letzter = _zeit(self._status.get("letzter_takt"))
        if letzter is None:
            return False
        return (jetzt - letzter).total_seconds() <= max(300, 2 * self.takt_sekunden)

    def status_daten(self, jetzt_wert: datetime | None = None) -> dict[str, Any]:
        jetzt = jetzt_wert or self._jetzt()
        snapshot = ressourcen_snapshot(self.db)
        aktiv = self._takt_aktiv(jetzt)
        letzter = _zeit(self._status.get("letzter_takt"))
        jobs: list[dict[str, Any]] = []
        warnungen: list[dict[str, str]] = []

        for job in self.jobs:
            status = self._job_status(job.name)
            naechster = _zeit(status.get("naechster_versuch"))
            if naechster is None:
                zustand = "bereit"
            elif naechster > jetzt:
                zustand = ("backoff" if int(status.get("fehlschluesse") or 0)
                           else "wartet")
            elif int(status.get("fehlschluesse") or 0):
                zustand = "fehler"
            else:
                zustand = "faellig"
            eintrag = {
                "name": job.name,
                "titel": job.titel,
                "zustand": zustand,
                "intervall_sekunden": job.intervall_sekunden,
                "ressourcen_intensiv": job.ressourcen_intensiv,
                "letzter_start": status.get("letzter_start"),
                "letzter_erfolg": status.get("letzter_erfolg"),
                "letzter_fehler": status.get("letzter_fehler"),
                "letzter_status": status.get("letzter_status"),
                "fehlschluesse": int(status.get("fehlschluesse") or 0),
                "backoff_sekunden": int(status.get("backoff_sekunden") or 0),
                "naechster_versuch": status.get("naechster_versuch"),
                "uebersprungen": status.get("uebersprungen"),
                "uebersprungen_grund": status.get("uebersprungen_grund") or "",
            }
            jobs.append(eintrag)
            if int(status.get("fehlschluesse") or 0):
                letzter_fehler = status.get("letzter_fehler") or {}
                warnungen.append({
                    "stufe": "warnung",
                    "job": job.name,
                    "text": (f"{job.titel}: {int(status['fehlschluesse'])} "
                             f"Fehlversuch(e), Backoff "
                             f"{int(status.get('backoff_sekunden') or 0)} s"
                             + (f" ({letzter_fehler.get('text')})"
                                if letzter_fehler.get("text") else "")),
                })
            if naechster is not None and naechster < jetzt - timedelta(
                    seconds=max(300, job.intervall_sekunden)):
                warnungen.append({
                    "stufe": "warnung", "job": job.name,
                    "text": f"{job.titel} ist seit {_iso(naechster)} überfällig.",
                })

        if self.grenzen.max_db_mb > 0 and snapshot["db_mb"] >= self.grenzen.max_db_mb:
            warnungen.append({"stufe": "fehler", "job": "ressourcen",
                              "text": (f"Datenbank {snapshot['db_mb']:.1f} MB hat "
                                       f"das Limit {self.grenzen.max_db_mb:g} MB erreicht.")})
        if (self.grenzen.max_rss_mb > 0 and snapshot.get("rss_mb") is not None
                and snapshot["rss_mb"] >= self.grenzen.max_rss_mb):
            warnungen.append({"stufe": "fehler", "job": "ressourcen",
                              "text": (f"Prozess-RSS {snapshot['rss_mb']:.1f} MB hat "
                                       f"das Limit {self.grenzen.max_rss_mb:g} MB erreicht.")})
        frei = snapshot.get("freier_speicher_mb")
        if (self.grenzen.min_freier_speicher_mb > 0 and frei is not None
                and frei <= self.grenzen.min_freier_speicher_mb):
            warnungen.append({"stufe": "fehler", "job": "ressourcen",
                              "text": (f"Nur {frei:.1f} MB freier Speicher; Limit "
                                       f"{self.grenzen.min_freier_speicher_mb:g} MB.")})

        if letzter is None:
            takt_zustand = "aus"
            warnungen.append({
                "stufe": "info", "job": "takt",
                "text": ("Noch kein Takt ausgeführt. Dauerbetrieb starten mit "
                         "`serve --takt` oder `ORAKEL_TAKT=1`."),
            })
        elif aktiv:
            takt_zustand = "laeuft"
        else:
            takt_zustand = "ueberfaellig"
            warnungen.append({
                "stufe": "warnung", "job": "takt",
                "text": (f"Letzter Takt {_iso(letzter)}; der Hintergrund-Takt "
                         "läuft nicht oder ist blockiert."),
            })
        if self._status.get("letzter_takt_status") == "fehler":
            warnungen.append({"stufe": "warnung", "job": "takt",
                              "text": "Der letzte Takt hatte mindestens einen fehlgeschlagenen Job."})

        try:
            daten = {
                "artikel": int(self.db.artikel_statistik()["gesamt"]),
                "missionen": int(self.db.nexus_mission_statistik().get("gesamt") or 0),
                "intel": self.db.intel_statistik(),
            }
        except Exception:
            daten = {"artikel": 0, "missionen": 0, "intel": {}}
        try:
            historie = self.db.betrieb_laeufe(20)
            statistik = self.db.betrieb_statistik(24)
        except Exception:
            historie, statistik = [], {"stunden": 24, "gesamt": 0, "fehler": 0,
                                       "uebersprungen": 0}

        ok = not any(w["stufe"] in ("fehler", "warnung") for w in warnungen)
        return {
            "ok": ok,
            "generiert": _iso(jetzt),
            "takt": {
                "status": takt_zustand,
                "aktiv": aktiv,
                "letzter": self._status.get("letzter_takt"),
                "letzter_status": self._status.get("letzter_takt_status"),
                "dauer_ms": int(self._status.get("letzter_takt_dauer_ms") or 0),
                "takt_nummer": int(self._status.get("takt_nummer") or 0),
                "intervall_sekunden": self.takt_sekunden,
            },
            "jobs": jobs,
            "ressourcen": {**snapshot, "limits": self.grenzen.als_dict()},
            "daten": daten,
            "statistik": statistik,
            "letzte_laeufe": historie,
            "warnungen": warnungen,
        }


def betrieb_status(cfg: Config, db: Facts,
                   jetzt_wert: datetime | None = None) -> dict[str, Any]:
    """Bequemer, seiteneffektfreier Einstieg für API, CLI und Health."""
    return Betrieb(cfg, db).status_daten(jetzt_wert)


def betrieb_health(cfg: Config, db: Facts) -> dict[str, Any]:
    """Kompakte, nicht geheime Betriebszeile für /api/health."""
    daten = betrieb_status(cfg, db)
    return {
        "status": daten["takt"]["status"],
        "letzter_takt": daten["takt"]["letzter"],
        "jobs": len(daten["jobs"]),
        "warnungen": len(daten["warnungen"]),
        "db_mb": daten["ressourcen"]["db_mb"],
        "rss_mb": daten["ressourcen"].get("rss_mb"),
    }
