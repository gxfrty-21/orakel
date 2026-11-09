FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /data

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY orakel /app/orakel
COPY config.toml /app/config.toml
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
