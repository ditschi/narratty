# syntax=docker/dockerfile:1.7
# narratty image: the CLI plus everything a native render needs (VHS, ttyd, Chromium,
# ffmpeg, fonts, Kokoro and Piper with a default voice each) and the demo toolkit. ttyd is not
# packaged in Debian trixie, so its static release binary is used. Targets:
#   toolkit ghcr.io/ditschi/narratty-toolkit:<version>  (static demo tools, see below)
#   base    ghcr.io/ditschi/narratty:<version>

ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim-trixie
ARG RUST_IMAGE=docker.io/library/rust:1-trixie

# ── toolkit ───────────────────────────────────────────────────────────────────
# Statically linked demo tools (bat, eza, fd, ripgrep, jq, yazi, file, zsh, tmux), a Nerd
# Font for icons and recording defaults, for any Linux image:
#   COPY --from=ghcr.io/ditschi/narratty-toolkit:<version> / /usr/local/
# Built on the build platform; tmux, file and eza are cross-compiled, nothing is emulated.
FROM --platform=$BUILDPLATFORM ${RUST_IMAGE} AS toolkit-build
ARG TARGETARCH
RUN apt-get update \
 && apt-get install -y --no-install-recommends bison unzip xz-utils \
 && rm -rf /var/lib/apt/lists/*
COPY docker/toolkit /opt/toolkit
RUN /opt/toolkit/build.sh "${TARGETARCH:-amd64}"

FROM scratch AS toolkit
COPY --from=toolkit-build /toolkit/ /

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
ARG TTYD_VERSION=1.7.7
# Voices baked into the image, so it renders without network access.
ARG KOKORO_VOICES="af_heart"
ARG PIPER_VOICES="en_US-lessac-medium"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg chromium \
      fonts-jetbrains-mono fonts-dejavu-core \
      git less tree \
 && curl -fsSL -o /tmp/vhs.deb \
      "https://github.com/charmbracelet/vhs/releases/download/v${VHS_VERSION}/vhs_${VHS_VERSION}_${TARGETARCH:-amd64}.deb" \
 && apt-get install -y --no-install-recommends /tmp/vhs.deb \
 && case "${TARGETARCH:-amd64}" in arm64) ttyd_arch=aarch64 ;; *) ttyd_arch=x86_64 ;; esac \
 && curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${ttyd_arch}" \
 && chmod 0755 /usr/local/bin/ttyd \
 && ttyd --version \
 && rm -rf /var/lib/apt/lists/* /tmp/vhs.deb

COPY --from=toolkit / /usr/local/
RUN if command -v fc-cache >/dev/null; then fc-cache -f; fi

COPY --from=wheel /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/narratty-*.whl && rm /tmp/narratty-*.whl

ENV NARRATTY_IN_CONTAINER=1 \
    NARRATTY_DATA_DIR=/opt/narratty/data \
    NARRATTY_CACHE_DIR=/cache \
    VHS_NO_SANDBOX=true \
    YAZI_CONFIG_HOME=/usr/local/share/narratty/yazi \
    BAT_CONFIG_PATH=/usr/local/share/narratty/bat/config \
    HOME=/home/narratty \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 1000 --shell /bin/bash narratty \
 && mkdir -p /opt/narratty/data /cache /work /out \
 && for voice in ${KOKORO_VOICES}; do narratty voices pull "$voice" --provider kokoro; done \
 && for voice in ${PIPER_VOICES}; do narratty voices pull "$voice" --provider piper; done \
 && chown -R narratty:narratty /cache /work /out /home/narratty \
 && chmod -R a+rX /opt/narratty \
 && chmod 1777 /cache /work /out /home/narratty

USER narratty
WORKDIR /work
ENTRYPOINT ["narratty"]
CMD ["--help"]
