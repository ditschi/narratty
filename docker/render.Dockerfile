# narratty image with the wheel of this checkout, so CI renders the docs videos with the
# code being documented (.github/actions/render-docs-videos). Build context: dist/.
ARG BASE=ghcr.io/ditschi/narratty:edge
FROM ${BASE}
USER root
COPY narratty-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/narratty-*.whl && rm /tmp/narratty-*.whl
USER narratty
