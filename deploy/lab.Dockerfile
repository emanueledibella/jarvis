FROM python:3.12.15-slim-trixie AS python-sandbox
RUN pip install --no-cache-dir numpy==2.5.4 pandas==3.1.0 matplotlib==3.11.2 defusedxml==0.7.1 \
    && groupadd --gid 10001 sandbox && useradd --uid 10001 --gid 10001 sandbox
WORKDIR /worker
COPY src/jarvis/python_worker.py src/jarvis/health_parser.py ./
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-I", "/worker/python_worker.py"]

FROM python:3.12.15-slim-trixie AS browser-sandbox
RUN pip install --no-cache-dir playwright==1.64.1 \
    && python -m playwright install --with-deps chromium \
    && groupadd --gid 10001 sandbox && useradd --uid 10001 --gid 10001 sandbox \
    && chmod -R a+rX /root/.cache/ms-playwright && mv /root/.cache/ms-playwright /opt/browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /worker
COPY src/jarvis/browser_worker.py ./
USER 10001:10001
ENTRYPOINT ["python", "-I", "/worker/browser_worker.py"]

FROM docker:29-cli AS docker-cli
FROM python:3.12.15-slim-trixie AS broker
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /app
COPY src/jarvis/__init__.py src/jarvis/sandbox.py src/jarvis/sandbox_broker.py ./jarvis/
RUN groupadd --gid 10001 broker && useradd --uid 10001 --gid 10001 --create-home broker \
    && mkdir -p /run/jarvis-sandbox && chown 10001:10001 /run/jarvis-sandbox
USER 10001:10001
ENTRYPOINT ["python", "-m", "jarvis.sandbox_broker"]
