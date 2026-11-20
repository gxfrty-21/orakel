# Basis-Image auf Digest gepinnt: gleiche Bytes bei jedem Build, unabhaengig
# davon, wann python:3.12-slim zuletzt neu gebaut wurde.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    ORAKEL_SEED_DB=/app/seed/orakel-seed.db

WORKDIR /data

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY orakel /app/orakel
COPY scripts/pruefe_backup.py /app/scripts/pruefe_backup.py
COPY config.toml /app/config.toml
# Seed-DB für den Erststart; der Entrypoint importiert sie nur in ein leeres Volume.
COPY seed /app/seed
COPY docker-entrypoint.sh /usr/local/bin/orakel-entrypoint

RUN chmod 755 /usr/local/bin/orakel-entrypoint \
    && groupadd --system orakel \
    && useradd --system --gid orakel --home-dir /data --shell /bin/false orakel \
    && mkdir -p /data \
    && chown -R orakel:orakel /data

USER orakel

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '3000') + '/api/health', timeout=4)"

ENTRYPOINT ["orakel-entrypoint"]
