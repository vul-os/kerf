# ── Kerf backend — monorepo Dockerfile ───────────────────────────────────────
#
# Build context is the repo root (.).
#
# Persona extras (install what you need for each pod type):
#
#   api-only      stateless API gateway + chat, no heavy compute
#   mech          full mechanical CAD stack
#   electronics   EDA / PCB / SPICE stack
#   bim           building information modelling stack
#   full          everything (monolith / dev)
#   compute-only  heavy compute workers only (no auth/API, behind internal LB)
#
# Override at build time:
#   docker build --build-arg KERF_PERSONA=mech -t kerf-mech .
#
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

ARG KERF_PERSONA=full

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the monorepo root pyproject.toml (meta-package with persona extras)
# and all plugin packages so pip can install editable local packages.
COPY pyproject.toml ./
COPY packages/ ./packages/
# backend/ still hosts shared tools/, workers/, geom/, utils/, distributors/
# (transitional — see backend/README.md)
COPY backend/ ./backend/

# Install the selected persona.  pip resolves all workspace package
# dependencies via the packages/ tree (no network needed for local deps).
RUN pip install --no-cache-dir -e ".[$KERF_PERSONA]"

# Optional: also install backend/requirements.txt for shared helpers that
# have not yet been absorbed into plugin packages.
RUN pip install --no-cache-dir -r backend/requirements.txt

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
# Tell the server where the legacy tools/ tree lives until it's fully split.
ENV PYTHONPATH=/app/backend

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/healthz || exit 1

# kerf-server is the console_script installed by packages/kerf-core.
CMD ["kerf-server", "--host", "0.0.0.0", "--port", "8080"]
