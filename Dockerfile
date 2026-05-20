# syntax=docker/dockerfile:1.7
#
# Multi-Stage-Build für meteoswiss-mcp (PR-4: SEC-007, SCALE-004, SCALE-006).
# Stage 1 baut ein wheel; Stage 2 installiert es unter unprivileged user.

ARG PYTHON_VERSION=3.13

# ---------- Stage 1: Builder ----------
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

# pyproject + Quellen reichen — hatchling baut ein PEP-517-Wheel
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip build \
    && python -m build --wheel --outdir /wheels

# ---------- Stage 2: Runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Non-root User (SEC-007: kein Container-as-root)
RUN groupadd --system --gid 10001 mcp \
    && useradd --system --uid 10001 --gid mcp --home /home/mcp --create-home mcp

WORKDIR /home/mcp

# Wheel + Laufzeit-Dependencies installieren
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels /root/.cache

# Defaults für Container-Deployment.
# MCP_HOST=0.0.0.0 ist nur mit MCP_ALLOW_ANY_HOST=1 erlaubt — PR-1 verlangt
# expliziten Opt-In; in Containern ist das genau gewollt.
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_ALLOW_ANY_HOST=1 \
    MCP_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Docker-native HEALTHCHECK — Render nutzt zusätzlich `healthCheckPath` in render.yaml
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)"

USER mcp:mcp

ENTRYPOINT ["meteoswiss-mcp"]
