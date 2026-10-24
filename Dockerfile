# ==============================================================================
# ReliantHook-Engine: High-Throughput Resilient Webhook Dispatch Gateway
# ==============================================================================
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY relianthook ./relianthook
RUN pip install --no-cache-dir -e .

EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8081/health || exit 1

ENTRYPOINT ["relianthook", "serve", "--host", "0.0.0.0", "--port", "8081"]
