FROM python:3.12-alpine
# hadolint ignore=DL3013 — pyyaml is a leaf dep with a stable API; not pinning intentionally
RUN pip install --no-cache-dir 'pyyaml>=6.0,<7.0'
WORKDIR /app
COPY router.py routing.yaml /app/
ENV ROUTING_FILE=/app/routing.yaml \
    LISTEN_PORT=8088
EXPOSE 8088
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -qO- http://localhost:8088/healthz || exit 1
CMD ["python3", "/app/router.py"]
