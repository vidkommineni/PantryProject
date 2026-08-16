# What's In My Pantry

An app that takes the ingredients you have on hand and returns recipes you can actually cook. It runs entirely on your own machine — zero external API calls at runtime, no quotas, no keys. Recipes come from the Kaggle **"Food.com Recipes and Reviews"** dataset loaded into SQLite, with a checked-in fixture database so the app works immediately.

For the full implementation notes, API reference, feature history, and project layout, see [`app/TECHNICAL_NOTES.md`](app/TECHNICAL_NOTES.md).

## Quick start

1. Install dependencies:
   ```bash
   cd app/backend
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Run the app:
   ```bash
   python app.py
   ```
   Open http://localhost:5000

3. Run tests from the project root:
   ```bash
   source app/backend/venv/bin/activate
   python -m pytest tests/
   ```

## What's implemented

- Fully local Flask backend with SQLite recipe and user-preference databases
- Plain HTML/CSS/JS frontend served by Flask, with no frontend build step
- Ingredient search with autocomplete, serving scaling, time filters, diets, intolerances, staples, spice inventory, favorites, and exclusions
- Local recipe ranking with weighted missing ingredients, max-missing overflow, sorting, ratings, and Tier-1 nutrition
- Strict protein matching so searches like "chicken" do not return pork, shrimp, or anchor-free recipes by accident
- ETL pipeline for building the full Food.com recipe database, plus a checked-in 50-recipe fixture database for local development and tests

## Running with Docker

Docker is optional — the venv workflow above still works unchanged. The image
pins Python 3.11 and bundles `data/fixtures.db`, so it runs with no setup.

```bash
# Production-shaped: gunicorn, non-root, healthchecked
docker compose up --build                 # → http://localhost:5000
docker compose down                       # stop; saved prefs survive
docker compose down -v                    # stop and wipe saved prefs

# Development: Flask reloader, source bind-mounted, edits apply live
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**How the two databases are handled.** They have different lifecycles, so they
are wired differently:

| Database | Where it lives | How the container gets it |
|---|---|---|
| `data/pantry.db` (~1.1 GB, from the ETL) | Your disk | Bind-mounted read-only at `/app/data`. Never copied into the image. |
| `data/fixtures.db` (110 KB) | Baked into the image | Automatic fallback when `pantry.db` is absent, so the image runs standalone. |
| `app/backend/pantry.db` (staples, spices, favorites, exclusions) | Named volume `pantry-userdata` | Written at runtime; survives `down` and rebuilds. |

`recipe_store.py` already resolved the recipe DB in that order, so nothing
changed there. Two small edits made this work:

- `db.py` now honours a `PANTRY_USER_DB` env var, defaulting to the old
  `app/backend/pantry.db` path. This moves the writable DB out of the source
  tree so a volume can persist it without shadowing the code.
- `gunicorn` was added to `requirements.txt`.

**Do not set `PANTRY_DB` in compose.** `recipe_store.db_path()` returns that
override without checking whether the file exists, which would break the
fixtures fallback. Letting it resolve naturally against the mounted `data/`
directory gives you the full DB when it's there and fixtures when it isn't.

**The ETL stays outside Docker.** `etl/run_all.py` needs pandas, pyarrow,
kagglehub and a Kaggle credential, none of which belong in the app image. Build
`data/pantry.db` in your venv as before; the container picks it up on the next
`up` via the bind mount.

**`.dockerignore` matters here.** The project directory is roughly 1.9 GB
(`data/raw/` alone is ~820 MB of CSVs plus a 179 MB parquet, and there's a
committed `app/backend/venv/`). Docker sends the whole build context to the
daemon on every build; the ignore file brings that down to about 300 KB.

## Useful commands

```bash
# Run locally
cd app/backend
source venv/bin/activate
python app.py

# Run tests from the project root
python -m pytest tests/

# Rebuild the fixture database after schema changes
python etl/build_fixtures.py

# Build the full recipe database once
pip install pandas pyarrow kagglehub
python etl/run_all.py
```
