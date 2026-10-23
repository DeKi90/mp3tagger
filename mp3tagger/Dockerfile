# syntax=docker/dockerfile:1
#
# One file, two images:
#
#   docker build --target standalone    -t mp3tagger .     plain Docker / NAS / compose
#   docker build                        -t mp3tagger-ha .  the Home Assistant app (default target)
#
# Home Assistant builds the LAST stage, so `homeassistant` has to stay at the bottom. The base is
# the official Python image (multi-arch: amd64 and arm64) because the project needs Python 3.14.

ARG PYTHON_VERSION=3.14

# --- dependencies and the package, installed into a venv ---------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv && pip install poetry
WORKDIR /build
# Dependencies first, exactly as locked: this layer is only rebuilt when the lock file changes.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root
COPY src ./src
RUN pip install --no-deps .

# --- what both images share ---------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH
COPY --from=builder /opt/venv /opt/venv

# --- plain Docker image -------------------------------------------------------------------------
FROM base AS standalone
# Mount your music at /music. Run with --user "$(id -u):$(id -g)" so tag changes are written with
# the permissions your files already have.
ENV MP3TAGGER_HOST=0.0.0.0 \
    MP3TAGGER_PORT=8080 \
    MP3TAGGER_ROOTS=/music \
    HOME=/tmp
EXPOSE 8080
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['MP3TAGGER_PORT'], timeout=4)"]
CMD ["mp3tagger"]

# --- Home Assistant app image (must stay the last stage) ----------------------------------------
FROM base AS homeassistant
# Supervisor passes these when it builds; naming them keeps the build log free of warnings.
ARG BUILD_ARCH
ARG BUILD_VERSION
# Runs as root so it can write tags to files in /media and /share, like other apps do. The
# options from Home Assistant are read from /data/options.json; the web UI is on the ingress port.
EXPOSE 8099
CMD ["mp3tagger-ha"]
