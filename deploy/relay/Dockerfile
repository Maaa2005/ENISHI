FROM python:3.12-slim AS resolver

WORKDIR /source
RUN pip install --no-cache-dir uv==0.11.29
COPY pyproject.toml uv.lock ./
COPY services/local-core/pyproject.toml services/local-core/pyproject.toml
COPY services/relay/pyproject.toml services/relay/pyproject.toml
COPY services/enishi-mcp/pyproject.toml services/enishi-mcp/pyproject.toml
RUN uv export --quiet --locked --package enishi-relay --no-dev --no-emit-project \
    --output-file /requirements.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 enishi \
    && useradd --system --uid 10001 --gid enishi --home-dir /nonexistent enishi

WORKDIR /app
COPY --from=resolver /requirements.txt ./requirements.lock
COPY services/relay/relay ./relay
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && mkdir -p /var/lib/enishi-relay \
    && chown -R enishi:enishi /var/lib/enishi-relay

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"]

CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
