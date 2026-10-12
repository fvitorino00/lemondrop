# syntax note: no build toolchain here, deliberately.
#
# This image installs pure-Python dependencies that all ship prebuilt wheels for
# CPython 3.12 on linux/amd64, so pip never needs to compile anything. There is
# no gcc, no build-essential, no cargo. Adding them would add ~150MB to the
# image and buy nothing. (llama.cpp needs a toolchain to build; this service
# does not build anything — it calls services that are already built.)

FROM python:3.12-slim

WORKDIR /app

# ── Layer-caching order ───────────────────────────────────────────────────────
# requirements.txt is copied and installed BEFORE the application source. Docker
# caches each instruction separately, and it can only reuse a cached layer if
# every input to that layer is unchanged.
#
# Copying the app first would make every single line of app code invalidate the
# pip-install layer, so a one-word change to main.py would trigger a full
# re-download and re-install of every dependency. Copying the pinned dependency
# list first means that layer is rebuilt only when requirements.txt itself
# changes — which, because everything is pinned exactly, is rare and always
# intentional.
COPY requirements.txt ./

# --no-cache-dir: pip's HTTP cache buys nothing inside a single-purpose image,
# and leaving it in the layer permanently adds its size to the final image.
RUN pip install --no-cache-dir -r requirements.txt

# Only now does the application source enter the build.
COPY app/ ./app/

# EXPOSE is DOCUMENTATION ONLY. It publishes nothing. It opens nothing. It does
# not even make the port reachable — Docker's network is not gated on it. Its
# one effect is to record intent ("this process listens here") and to give
# tooling such as `docker run -P` a port to pick from. The port actually reaches
# the host only via a `ports:` key in docker-compose.yml, which is why the
# compose `ports:` entry below is the milestone's real network decision and this
# line is not.
EXPOSE 8000

# Exec form: no shell, so the process receives signals directly. That is what
# lets `docker compose stop` reach uvicorn, which in turn is what lets it shut
# down gracefully instead of being SIGKILLed after the timeout.
#
# --host 0.0.0.0, NOT 127.0.0.1. uvicorn binds the loopback interface by
# default, and loopback inside a container is reachable only from inside that
# container. The API would then answer `docker compose exec api curl ...` and
# refuse every connection from the host and from the other services. 0.0.0.0
# binds all interfaces, which is what makes the service reachable on the compose
# network at its container name.
#
# Port 8000 is literal because exec-form CMD performs no shell expansion — there
# is no shell here to expand anything. This is the same constraint that pins
# RERANKER_INTERNAL_PORT to 8080: the port a process binds is fixed by its
# command line. API_INTERNAL_PORT in .env must therefore stay 8000, and the
# compose `ports:` mapping is what makes the host side configurable.
#
# Run as root, deliberately. A non-root user is a real hardening step and it is
# deferred on purpose rather than forgotten: this phase adds no volume, no
# secrets and no user-supplied code, so there is nothing here for it to protect.
# It belongs in the same commit as the first thing that does.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
