# dataset-profiler — built on techneos/tool-runtime.
#
# The base provides python + techneos-tool-runtime + the generic runner ENTRYPOINT.
# This tool needs WeasyPrint's native libs (Pango/Cairo/GDK-pixbuf) at runtime,
# so it installs them itself; `pip install .` brings pandas/matplotlib/weasyprint.

# BASE_REGISTRY lets a build prefix the base image with a remote registry.
# Empty default works for local docker / OrbStack.
ARG BASE_REGISTRY=
# Pin a specific base version (never `latest`) for reproducible rebuilds. Keep
# in sync with packages/tool-runtime/pyproject.toml ([project].version).
ARG BASE_TAG=0.1.0
FROM ${BASE_REGISTRY}techneos/tool-runtime:${BASE_TAG}

LABEL org.opencontainers.image.title="dataset-profiler"
LABEL org.opencontainers.image.description="Dataset profiler — HTML/PDF summaries of tabular data"
LABEL techneos.tool="dataset-profiler"

# WeasyPrint needs Pango, Cairo, and GDK-pixbuf at runtime. (libfontconfig is
# already in the base; these are the WeasyPrint-specific additions.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libcairo2 \
    libffi8 \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV ENTRYPOINT_SPEC=dataset_profiler.core:run
