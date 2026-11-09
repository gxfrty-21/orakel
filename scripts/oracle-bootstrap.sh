#!/usr/bin/env bash
# Orakel auf einer frischen Ubuntu-VM (Oracle Always Free, Arm) einrichten.
# Idempotent: vorhandene Installation, .env und Daten werden nicht überschrieben.
#
# Aufruf (als root oder mit sudo):
#   sudo REPO_URL=git@github.com:USER/REPO.git ORAKEL_DOMAIN=name.duckdns.org \
#        bash scripts/oracle-bootstrap.sh
#
# Voraussetzungen: Ubuntu 22.04/24.04, DNS zeigt bereits auf diese IP,
# Ports 80/443 in der OCI-Security-List offen, Repo-Zugang per Deploy-Key.
set -euo pipefail

REPO_URL="${REPO_URL:-}"
ORAKEL_DOMAIN="${ORAKEL_DOMAIN:-}"
ZIEL="${ZIEL:-/srv/orakel}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }
info()   { echo "==> $*"; }

[ "$(id -u)" -eq 0 ] || fehler "bitte als root bzw. mit sudo ausführen"
[ -n "$REPO_URL" ]   || fehler "REPO_URL fehlt (z. B. git@github.com:user/orakel.git)"
[ -n "$ORAKEL_DOMAIN" ] || fehler "ORAKEL_DOMAIN fehlt (z. B. orakel.duckdns.org)"

info "Pakete und Docker installieren"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg git openssl ufw
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
else
  info "Docker ist bereits installiert"
fi
docker compose version >/dev/null || fehler "docker compose plugin fehlt"
systemctl enable --now docker >/dev/null 2>&1 || true

info "Firewall: 22, 80, 443"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
fi
# Oracle-Ubuntu-Images bringen eigene iptables-Regeln mit, die ufw umgehen.
if [ -f /etc/iptables/rules.v4 ]; then
  for p in 80 443; do
    iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 5 -p tcp --dport "$p" -j ACCEPT
  done
  command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
  info "iptables-Regeln ergänzt (OCI-Image)"
fi

info "Repository nach $ZIEL"
mkdir -p "$(dirname "$ZIEL")"
if [ ! -d "$ZIEL/.git" ]; then
  git clone "$REPO_URL" "$ZIEL"
else
  git -C "$ZIEL" pull --ff-only
fi

info ".env vorbereiten"
if [ ! -f "$ZIEL/.env" ]; then
  cp "$ZIEL/.env.example" "$ZIEL/.env"
  PASS="$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 24)"
  sed -i "s|^ORAKEL_DOMAIN=.*|ORAKEL_DOMAIN=${ORAKEL_DOMAIN}|" "$ZIEL/.env"
  sed -i "s|^ORAKEL_AUTH_PASS=.*|ORAKEL_AUTH_PASS=${PASS}|" "$ZIEL/.env"
  chmod 600 "$ZIEL/.env"
  info "Passwort erzeugt und nur in $ZIEL/.env gespeichert (chmod 600)"
  info "Anzeigen mit: sudo grep ORAKEL_AUTH_PASS $ZIEL/.env"
else
  info ".env existiert bereits — unverändert"
fi

info "DNS prüfen"
IP_VM="$(curl -fsS -m 10 https://api.ipify.org || echo '?')"
IP_DNS="$(getent ahostsv4 "$ORAKEL_DOMAIN" | awk 'NR==1 {print $1}' || true)"
if [ -n "$IP_DNS" ] && [ "$IP_DNS" != "$IP_VM" ]; then
  echo "WARNUNG: $ORAKEL_DOMAIN zeigt auf $IP_DNS, diese VM ist $IP_VM."
  echo "         Caddy kann erst ein Zertifikat holen, wenn DNS stimmt."
fi

info "Stack bauen und starten"
cd "$ZIEL"
docker compose up -d --build

info "Warten auf Healthcheck (bis 5 Minuten)"
ok=0
for _ in $(seq 1 60); do
  if curl -fsS -m 5 "https://${ORAKEL_DOMAIN}/api/health" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 5
done

if [ "$ok" -eq 1 ]; then
  echo
  echo "Fertig. Dashboard: https://${ORAKEL_DOMAIN}"
  echo "Login:            orakel (Passwort in ${ZIEL}/.env)"
  curl -fsS "https://${ORAKEL_DOMAIN}/api/health"; echo
else
  echo "Healthcheck noch nicht grün. Logs:"
  docker compose logs --tail 40 caddy orakel || true
  echo "Häufigste Ursachen: DNS falsch, Port 80/443 in der OCI-Security-List zu,"
  echo "oder iptables blockt (siehe docs/spider/ORACLE-MIGRATION.md)."
  exit 1
fi
