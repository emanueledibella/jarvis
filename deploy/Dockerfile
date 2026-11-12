FROM node:22-alpine AS frontend
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.15-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    JARVIS_DATA_DIR=/data JARVIS_UI_DIR=/app/web/dist JARVIS_PROFILE=cloud \
    LANGSMITH_TRACING=false
WORKDIR /app
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates age \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir uv==0.13.5
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable \
    && groupadd --gid 10001 jarvis && useradd --uid 10001 --gid 10001 --create-home jarvis \
    && mkdir -p /data /run/jarvis-worker && chown -R 10001:10001 /data /run/jarvis-worker
COPY --from=frontend /build/dist ./web/dist
USER 10001:10001

FROM runtime AS core
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD ["/app/.venv/bin/python", "-c", "import os,urllib.request,urllib.parse; r=urllib.request.Request('http://127.0.0.1:8765/health',headers={'Host':urllib.parse.urlsplit(os.environ['JARVIS_REMOTE_PUBLIC_URL']).netloc}); assert urllib.request.urlopen(r,timeout=3).status==200"]
CMD ["/app/.venv/bin/jarvis", "server", "--bind", "0.0.0.0"]

FROM runtime AS document-worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s CMD ["/app/.venv/bin/python", "-c", "import asyncio,os;from jarvis.document_service import worker_request;assert asyncio.run(worker_request(os.environ.get('JARVIS_DOCUMENT_WORKER_SOCKET','/run/jarvis-worker/parser.sock'),{'health':True}))['status']=='ok'"]
CMD ["/app/.venv/bin/python", "-m", "jarvis.document_service"]
