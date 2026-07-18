FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 enishi \
    && useradd --system --uid 10001 --gid enishi --home-dir /nonexistent enishi

WORKDIR /app
COPY services/relay/pyproject.toml ./pyproject.toml
COPY services/relay/relay ./relay
RUN pip install --no-cache-dir . \
    && mkdir -p /var/lib/enishi-relay \
    && chown -R enishi:enishi /var/lib/enishi-relay

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"]

CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
