#!/usr/bin/env bash
# Reproduzierbares Playwright-Chromium-Setup für Ubuntu 24.04 amd64 ohne sudo.
#
# Systembibliotheken und Fonts werden als .deb heruntergeladen und nach
# .playwright-local/ entpackt. Es werden keine Systempakete installiert; die
# entpackten Dateien bleiben im Projektordner. Abschliessend werden der
# Chromium-Start und die geladenen Font-Metriken im Browser geprüft.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL="${PLAYWRIGHT_LOCAL_DIR:-$ROOT/.playwright-local}"
APT="$LOCAL/apt"
DEBS="$APT/debs"
LIBDIR="$LOCAL/usr/lib/x86_64-linux-gnu"
ENV_FILE="$LOCAL/env.sh"
FONTCONFIG_FILE="$LOCAL/fonts.conf"

if [ -r /etc/os-release ]; then
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "FEHLER: Dieses Setup ist für Ubuntu 24.04 vorgesehen (gefunden: ${PRETTY_NAME:-unbekannt})." >&2
    exit 1
  fi
fi
if [ "$(dpkg --print-architecture)" != "amd64" ]; then
  echo "FEHLER: Dieses Setup unterstützt nur die Ubuntu-Architektur amd64." >&2
  exit 1
fi
for werkzeug in apt-get dpkg-deb node npm; do
  if ! command -v "$werkzeug" >/dev/null 2>&1; then
    echo "FEHLER: Benötigtes Werkzeug fehlt: $werkzeug" >&2
    exit 1
  fi
done
if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; then
  echo "FEHLER: Node.js >= 20 wird benötigt." >&2
  exit 1
fi

mkdir -p "$LOCAL" "$DEBS" "$APT/lists/partial" "$APT/cache/archives/partial" "$LOCAL/fontcache"
APT_OPTS=(
  -o "Dir::State::Lists=$APT/lists"
  -o "Dir::Cache=$APT/cache"
  -o "APT::Get::List-Cleanup=0"
)

echo "1/4: Playwright-Abhängigkeit installieren"
(cd "$ROOT/scripts" && npm ci)

echo "2/4: Chromium installieren"
(cd "$ROOT/scripts" && ./node_modules/.bin/playwright install chromium)

echo "3/4: Lokale Laufzeitbibliotheken und Fonts entpacken"
apt-get "${APT_OPTS[@]}" update
(
  cd "$DEBS"
  apt-get "${APT_OPTS[@]}" download \
    libnspr4 libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 \
    libcups2t64 libdrm2 libxkbcommon0 libatspi2.0-0t64 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxrender1 \
    libgbm1 libasound2t64 libpango-1.0-0 libcairo2 \
    libx11-6 libxcb1 libxext6 libxi6 libxtst6 \
    libwayland-client0 libwayland-server0 libexpat1 libglib2.0-0t64 \
    fonts-dejavu-core fontconfig-config
)
for deb in "$DEBS"/*.deb; do
  [ -e "$deb" ] || continue
  dpkg-deb -x "$deb" "$LOCAL"
done

cat > "$FONTCONFIG_FILE" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>$LOCAL/usr/share/fonts</dir>
  <cachedir>$LOCAL/fontcache</cachedir>
  <include ignore_missing="yes">$LOCAL/etc/fonts/conf.d</include>
</fontconfig>
EOF

cat > "$ENV_FILE" <<EOF
export PLAYWRIGHT_LOCAL_ROOT="$LOCAL"
export LD_LIBRARY_PATH="$LIBDIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export FONTCONFIG_FILE="$FONTCONFIG_FILE"
export FONTCONFIG_PATH="$LOCAL/etc/fonts"
EOF

FONT_PFAD="$(find "$LOCAL/usr/share/fonts" -type f -name 'DejaVuSans.ttf' -print -quit)"
if [ -z "$FONT_PFAD" ]; then
  echo "FEHLER: DejaVuSans.ttf wurde nicht entpackt." >&2
  exit 1
fi

echo "4/4: Chromium-Start und Font-Metriken prüfen"
(
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  cd "$ROOT/scripts"
  FONT_PFAD="$FONT_PFAD" node --input-type=module -e '
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const fontUrl = "data:font/ttf;base64," + readFileSync(process.env.FONT_PFAD).toString("base64");
const metrik = await page.evaluate(async (url) => {
  const face = new FontFace("DejaVuSansProbe", "url(" + url + ")");
  document.fonts.add(face);
  await face.load();
  const el = document.createElement("span");
  el.textContent = "Font-Metrik Ω";
  el.style.cssText = "font: 32px DejaVuSansProbe; display: inline-block";
  document.body.append(el);
  const rechteck = el.getBoundingClientRect();
  const ctx = document.createElement("canvas").getContext("2d");
  ctx.font = "32px DejaVuSansProbe";
  return {
    status: face.status,
    geladen: document.fonts.check("32px DejaVuSansProbe"),
    breite: Math.round(rechteck.width * 100) / 100,
    hoehe: Math.round(rechteck.height * 100) / 100,
    textBreite: Math.round(ctx.measureText("Font-Metrik Ω").width * 100) / 100,
  };
}, fontUrl);
if (metrik.status !== "loaded" || !metrik.geladen || metrik.breite <= 0 || metrik.hoehe <= 0 || metrik.textBreite <= 0) {
  throw new Error("Font-Metriken fehlen: " + JSON.stringify(metrik));
}
console.log("Playwright-Chromium und Font-Metriken OK (" + metrik.breite + " × " + metrik.hoehe + " px, Text " + metrik.textBreite + " px)");
await browser.close();
'
)

echo
echo "Lokales Playwright-Setup fertig."
echo "Umgebung aktivieren:"
echo "  source ${ENV_FILE#"$ROOT"/}"
