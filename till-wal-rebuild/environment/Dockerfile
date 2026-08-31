FROM python:3.13-slim-bookworm

WORKDIR /app
COPY data /app/data
COPY feed/payload.nclog /opt/nyota-feed/cold
COPY feed/serve.py /opt/nyota-feed/serve.py
COPY feed/start.sh /opt/nyota-feed/start.sh
RUN chmod +x /opt/nyota-feed/start.sh && mkdir -p /app/output
ENTRYPOINT ["/opt/nyota-feed/start.sh"]
