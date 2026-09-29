# syntax=docker/dockerfile:1.7
# narratty image: the CLI plus everything a native render needs (VHS, ttyd, Chromium,
# ffmpeg, fonts, Piper with a default voice). Targets:
#   base    ghcr.io/ditschi/narratty:<version>
#   kokoro  ghcr.io/ditschi/narratty:<version>-kokoro  (adds kokoro-onnx and its model)

ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim-trixie

# ── wheel ─────────────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS wheel
# hatch-vcs reads the version from git, which is not in the build context.
ARG NARRATTY_VERSION=0.0.0.dev0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${NARRATTY_VERSION}
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /dist .

# ── base ──────────────────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS base
ARG TARGETARCH
ARG VHS_VERSION=0.12.1
# Voices baked into the image, so it renders without network access.
ARG PIPER_VOICES="en_US-lessac-medium"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg ttyd chromium \
      fonts-jetbrains-mono fonts-dejavu-core \
      git bat eza fd-find ripgrep jq less tree \
 && curl -fsSL -o /tmp/vhs.deb \
      "https://github.com/charmbracelet/vhs/releases/download/v${VHS_VERSION}/vhs_${VHS_VERSION}_${TARGETARCH:-amd64}.deb" \
 && apt-get install -y --no-install-recommends /tmp/vhs.deb \
 && ln -s /usr/bin/batcat /usr/local/bin/bat \
 && ln -s /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/* /tmp/vhs.deb

COPY --from=wheel /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/narratty-*.whl && rm /tmp/narratty-*.whl

ENV NARRATTY_IN_CONTAINER=1 \
    NARRATTY_DATA_DIR=/opt/narratty/data \
    NARRATTY_CACHE_DIR=/cache \
    VHS_NO_SANDBOX=true \
    HOME=/home/narratty \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 1000 --shell /bin/bash narratty \
 && mkdir -p /opt/narratty/data /cache /work /out \
 && for voice in ${PIPER_VOICES}; do narratty voices pull "$voice" --provider piper; done \
 && chown -R narratty:narratty /cache /work /out /home/narratty \
 && chmod -R a+rX /opt/narratty \
 && chmod 1777 /cache /work /out /home/narratty

USER narratty
WORKDIR /work
ENTRYPOINT ["narratty"]
CMD ["--help"]

# ── kokoro ────────────────────────────────────────────────────────────────────
FROM base AS kokoro
ARG KOKORO_VOICE=af_heart
USER root
RUN pip install --no-cache-dir "kokoro-onnx>=0.6" \
 && narratty voices pull "${KOKORO_VOICE}" --provider kokoro \
 && chmod -R a+rX /opt/narratty
USER narratty
