# autodock-vina — built on techneos/tool-runtime.
#
# The base provides python + techneos-tool-runtime + the generic runner ENTRYPOINT.
# This tool needs the native AutoDock Vina (`vina`) and OpenBabel (`obabel`)
# binaries, so it installs them itself; `pip install .` brings RDKit + Meeko.

# BASE_REGISTRY lets a build prefix the base image with a remote registry.
# Empty default works for local docker / OrbStack.
ARG BASE_REGISTRY=
# Pin a specific base version (never `latest`) for reproducible rebuilds. Keep
# in sync with packages/tool-runtime/pyproject.toml ([project].version).
ARG BASE_TAG=0.1.0
FROM ${BASE_REGISTRY}techneos/tool-runtime:${BASE_TAG}

LABEL org.opencontainers.image.title="autodock-vina"
LABEL org.opencontainers.image.description="AutoDock Vina docking — rank molecules by binding affinity to a receptor"
LABEL techneos.tool="autodock-vina"

# AutoDock Vina (`vina`, `vina_split`) and OpenBabel (`obabel`) are native
# binaries this tool shells out to.
RUN apt-get update && apt-get install -y --no-install-recommends \
    autodock-vina \
    openbabel \
    && rm -rf /var/lib/apt/lists/* \
    && command -v vina && command -v obabel

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV ENTRYPOINT_SPEC=autodock_vina.docking:run
