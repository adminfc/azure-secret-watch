FROM python:3.12-slim

# Keep the image minimal: no compilers/build tools, no shell scripts pulled from
# the network. Only the read-only scanner and its Python dependencies.
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY azure_secret_watch ./azure_secret_watch

RUN useradd --create-home --uid 10001 watcher \
    && mkdir -p /data \
    && chown -R watcher:watcher /app /data

USER watcher

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=5m --timeout=5s --start-period=30s --retries=3 \
    CMD python -m azure_secret_watch.healthcheck || exit 1

ENTRYPOINT ["python", "-m", "azure_secret_watch"]
