# syntax=docker/dockerfile:1
#
# Østfoldbussen – multi-stage, non-root, ingen pip-avhengigheter.
# Base-image er pinnet til både tag og OCI-manifest-digest for reproduserbare bygg.
ARG PYTHON_IMAGE="python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34"

FROM ${PYTHON_IMAGE} AS build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv
WORKDIR /build
# Byggestadiet kompilerer alle moduler slik at syntaksfeil stopper bygget.
COPY app ./app
COPY prototype ./prototype
RUN python -m compileall -q app prototype && python -c "import app.config, app.server, prototype.journeys"

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv \
    LANG=C.UTF-8 \
    TZ=UTC
WORKDIR /srv

# Dedikert ikke-root bruker med fast uid/gid 10001 (matcher compose/host).
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/ostfoldbussen \
    && chown 10001:10001 /var/lib/ostfoldbussen

COPY --from=build --chown=10001:10001 /build/app ./app
COPY --from=build --chown=10001:10001 /build/prototype ./prototype

USER 10001:10001
EXPOSE 8000

# Ærlig helsesjekk: 503 eller feil => unhealthy. Ingen falsk HEALTHY.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "app"]
