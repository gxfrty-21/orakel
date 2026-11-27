"""Statische Prüfung der Scheduler-Registrierung (ohne echte Task-Anlage)."""
from __future__ import annotations

from pathlib import Path


def test_task_hat_einen_trigger_und_zwei_begrenzte_restarts():
    text = (Path(__file__).resolve().parents[1] / "scripts" /
            "windows_transport_task.ps1").read_text(encoding="utf-8")

    assert text.count("New-ScheduledTaskTrigger -Daily") == 1
    assert "Repetition" not in text
    assert "-StartWhenAvailable" in text
    assert "-MultipleInstances IgnoreNew" in text
    assert "-ExecutionTimeLimit (New-TimeSpan -Minutes 15)" in text
    assert "-RestartCount 2" in text
    assert "-RestartInterval (New-TimeSpan -Minutes 30)" in text


def test_task_startet_keinen_systemdienst_und_uebergibt_kein_secret():
    text = (Path(__file__).resolve().parents[1] / "scripts" /
            "windows_transport_task.ps1").read_text(encoding="utf-8")

    assert "-LogonType Interactive" in text
    assert "-RunLevel Limited" in text
    assert "SYSTEM" in text
    assert "ORAKEL_TRANSPORT_TOKEN" not in text
    assert "Authorization" not in text