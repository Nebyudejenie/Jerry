FROM python:3.12-alpine

# Pins: pyyaml/psycopg are version-floored. Alpine apks rely on rolling repo — accepted.
# hadolint ignore=DL3018,DL3013
RUN apk add --no-cache openssh-client ca-certificates curl bash \
 && pip install --no-cache-dir 'pyyaml>=6.0,<7.0' 'psycopg[binary]>=3.2,<4.0'

# Non-root user with a real home for .ssh
RUN addgroup -g 1000 terry \
 && adduser -D -u 1000 -G terry -h /home/terry terry \
 && mkdir -p /home/terry/.ssh /tmp/terry/approvals \
 && chown -R terry:terry /home/terry /tmp/terry \
 && chmod 700 /home/terry/.ssh

WORKDIR /app
COPY server.py /app/server.py
RUN chown -R terry:terry /app

# These get bind-mounted via compose:
#   /app/ssh_exec.py        (from scripts/ssh-framework/ssh_exec.py)
#   /app/audit_writer.py    (from scripts/utilities/audit_writer.py)
#   /app/memory_compactor.py(from scripts/utilities/memory_compactor.py)
#   /app/allowlists/        (from security/allowlists)
#   /home/terry/.ssh/       (key + known_hosts; host-side files must be chown 1000:1000)

ENV TERRY_ALLOWLIST_DIR=/app/allowlists \
    TERRY_RUNTIME_DIR=/tmp/terry \
    LISTEN_PORT=8090 \
    PYTHONUNBUFFERED=1

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD curl -sf http://localhost:8090/healthz || exit 1

USER terry
CMD ["python3", "/app/server.py"]
