# syntax=docker/dockerfile:1
#
# "What's In My Pantry" — multi-stage image.
#
#   base  shared layers: Python + dependencies + application code
#   dev   Flask reloader, expects the source bind-mounted over /app/app
#   prod  gunicorn, non-root user, healthcheck  (this is the default target)
#
# Build the production image:   docker build -t pantry-app .
# Build the dev image:          docker build --target dev -t pantry-app:dev .

###############################################################################
# base
###############################################################################
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies are installed BEFORE the code is copied, so editing a .py file
# reuses the cached pip layer instead of reinstalling everything.
COPY app/backend/requirements.txt ./app/backend/requirements.txt
RUN pip install --no-cache-dir -r app/backend/requirements.txt

# recipe_store.py computes DATA_DIR as <repo_root>/data by walking up three
# parents from its own file, so the container mirrors the repo layout exactly:
#   /app/app/backend   /app/app/frontend   /app/data
COPY app/ ./app/

# The 50-recipe fixture DB is baked in (110 KB) so the image runs with no
# mounts at all. The full 1.1 GB data/pantry.db is bind-mounted at runtime and
# takes precedence automatically when present.
COPY data/fixtures.db ./data/fixtures.db

# The user-preference DB (staples, spices, favorites, exclusions) is written at
# runtime, so it lives outside the source tree — that way a named volume can
# persist it without shadowing the application code.
ENV PANTRY_USER_DB=/app/userdata/pantry.db
RUN mkdir -p /app/userdata

# Backend modules import each other flat (`import db`, `import search`), so the
# working directory has to be the backend package root.
WORKDIR /app/app/backend

EXPOSE 5000

###############################################################################
# dev — live reload; compose bind-mounts ./app over /app/app
###############################################################################
FROM base AS dev

ENV FLASK_APP=app \
    FLASK_DEBUG=1

# Uses the Flask CLI rather than `python app.py` because the __main__ block
# binds to 127.0.0.1, which is unreachable from outside the container.
CMD ["flask", "run", "--host", "0.0.0.0", "--port", "5000", "--debug"]

###############################################################################
# prod — gunicorn, unprivileged, healthchecked
###############################################################################
FROM base AS prod

RUN useradd --create-home --uid 10001 pantry \
 && chown -R pantry:pantry /app/userdata
USER pantry

# Hits the static index route: proves the process is serving without touching
# either database. (curl isn't in python:slim, so this uses urllib.)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3).status == 200 else 1)"

# Two workers is plenty for a single-user app; SQLite handles concurrent reads
# fine, and threads absorb the slower search queries against the full corpus.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
