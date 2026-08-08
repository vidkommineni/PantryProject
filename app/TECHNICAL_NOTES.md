# What's In My Pantry (V4 — fully local)

An app that takes the ingredients you have on hand and returns recipes you can actually cook. **V4 runs entirely on your own machine — zero external API calls, no quotas, no keys.** Recipes come from the Kaggle **"Food.com Recipes and Reviews"** dataset (~500K recipes, with ingredient quantities, serving counts, per-serving nutrition, ratings, and image URLs) loaded into SQLite; Spoonacular is retired (spec Part III).

Local-storage-only (SQLite files, single user, no accounts) and text-entry only. See the Context specs (`../files/whats-in-my-pantry-spec-v3.md` and `../files/whats-in-my-pantry-spec-v4-addendum.md`) for the full feature spec and version history.

## Stack

- **Backend**: Python + Flask. Two SQLite databases:
  - `data/pantry.db` (or `data/fixtures.db` fallback) — the recipe database built by the ETL: recipes, ingredient vocabulary, inverted index, diet-exclusion sets, FTS5 autocomplete index.
  - `app/backend/pantry.db` — user preferences: staples, spice inventory, favorites, "never show me X" exclusions.
- **Frontend**: plain HTML/CSS/JS (no build step), served directly by Flask.

## Setup

1. Install dependencies:
   ```bash
   cd app/backend
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Run (works immediately against the checked-in 50-recipe `data/fixtures.db`):
   ```bash
   python app.py
   ```
   Open http://localhost:5000

3. Build the full recipe database (once; spec 10.3):
   ```bash
   pip install pandas pyarrow kagglehub
   python etl/run_all.py
   ```
   This downloads the Kaggle **Food.com Recipes and Reviews** dataset (`irkaal/foodcom-recipes-and-reviews`; needs a free Kaggle account — kagglehub reads `~/.kaggle/kaggle.json`) and builds `data/pantry.db`. The app automatically prefers it over the fixtures DB on next start. If you've already downloaded `recipes.parquet` (or `recipes.csv`) manually, drop it in `data/raw/` and the download step is skipped.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PANTRY_DB` | auto | Explicit path to a recipe DB (otherwise `data/pantry.db`, falling back to `data/fixtures.db`) |
| `PORT` | `5000` | Flask port |

That's the whole table now — no API keys, no cache toggles, no mock mode. The local DB *is* the cache and the mock (spec 14).

## What's implemented

### V1 (spec sections 1–6)
- Ingredient text box with local FTS5 autocomplete, serving size, time filter, diet + intolerance chips
- Staples whitelist (editable; excluded from gap analysis, still shown in ingredient lists)
- Spice inventory tab, merged into every search
- Recipe detail with instructions, description, rating, image, Food.com source link
- **Ingredient quantities with serving scaling (2.5)**: amounts are scaled server-side by `desiredServings / defaultServings` and formatted as mixed fractions ("1 1/2"); unparseable amounts pass through unscaled
- Nutrition on demand (Tier 1: the dataset's absolute per-serving values; multiplied by your serving count for totals)
- Shopping-list copy button, match % badge, sort toggle, favorites, empty states

### V2 — match quality (spec section 7)
- Ingredient normalization (7.2): descriptor stripping + synonym dictionary; canonical vocabulary now comes from the dataset itself
- Weighted re-ranking (7.3): `used / (used + weightedMissing)` with 0.0 staple / 0.25 spice / 1.0 core weights; tie-breakers: real missing count, ready time, then dataset rating (v3 bonus signal)
- Max-missing slider (7.4) with the "show more" overflow section
- Server-side ranking strategies (7.1): best match / fewest missing / fastest

### V3 — fully local architecture (spec Part III)
- **ETL pipeline** (`etl/`, spec 10.3): `load_recipes` → `build_ingredient_index` (vocabulary + inverted index) → `derive_diet_flags` (keyword flags + ingredient-scan flags + exclusion keyword sets). Ratings come pre-aggregated on the dataset, so there's no separate ratings step. Idempotent; orchestrated by `run_all.py`.
- **Search** (spec 11.1): inverted-index SQL over `recipe_ingredients`, exact ingredient-ID matching with a controlled cut-word expansion ("chicken" matches "chicken breasts" but never "chicken broth" or "chickpeas").
- **Hard diet enforcement** (spec 11.2): belt-and-suspenders — tag-derived flags (vegetarian/vegan) AND an indexed anti-join against `diet_exclusions` keyword sets; intolerances use the same anti-join. Applied before scoring, so an excluded recipe can never appear.
- **"Never show me X"** (spec 11.2): per-user excluded-ingredients list (Exclusions tab) applied as a hard anti-join on every search.
- **Autocomplete** (spec 11.3): FTS5 prefix query with rapidfuzz typo fallback.
- **Tier-1 nutrition** (spec 11.4): dataset per-recipe values. (Tier 2 — USDA FDC per-ingredient computation — is Phase 4, not yet built; `nutrition_cache` table is kept for it.)
- **Ratings as ranking signal** (spec 14): avg rating + count shown on cards and used as tie-breaker.

### V4 — anchor-ingredient matching (spec section 15)
- **Strict protein match**: when a user enters an anchor ingredient such as chicken, salmon, tofu, or protein powder, search applies a hard filter before scoring so results must feature that protein family.
- **No protein leakage by default**: a chicken search will not return pork, shrimp, or anchor-free recipes just because the side ingredients match well. The UI includes a "Strict protein match" checkbox; turning it off allows recipes with additional proteins.
- **Derivative ingredients are handled safely**: chicken broth, fish sauce, bacon bits, and similar flavor-base ingredients do not satisfy or trigger protein anchors.
- **Regression coverage**: V4 tests cover chicken-not-pork behavior, whey protein normalization, broth edge cases, strict/relaxed protein mode, and multi-anchor searches.

## Not yet implemented

- USDA FDC Tier-2 nutrition (spec 10.3 steps 5–6, 11.4)
- Phase 5: live pantry inventory with auto-depletion, receipt OCR, fridge-photo vision

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/staples` · POST `/api/staples` · DELETE `/api/staples/<name>` | staples whitelist |
| GET | `/api/spices` · POST `/api/spices/toggle` | spice inventory |
| GET | `/api/exclusions` · POST `/api/exclusions` · DELETE `/api/exclusions/<name>` | "never show me X" |
| GET | `/api/autocomplete?query=` | local FTS5 ingredient autocomplete |
| POST | `/api/search` | search recipes by ingredients + filters |
| GET | `/api/recipe/<id>?servings=` | full recipe detail |
| POST | `/api/recipe/<id>/nutrition` | Tier-1 per-serving nutrition (+ totals for your servings) |
| GET/POST | `/api/favorites` · DELETE `/api/favorites/<id>` | favorites |

### `POST /api/search`

Request body:

```json
{
  "ingredients": ["chicken breast", "broccoli", "rice"],
  "servings": 4,
  "maxReadyTime": 30,
  "diet": ["vegetarian"],
  "intolerances": ["dairy"],
  "useSpiceInventory": true,
  "strictProtein": true,
  "maxMissing": 2,
  "sort": "match"
}
```

`sort` is one of `match` / `missing` / `fastest` (spec 7.1). `strictProtein` defaults to `true`; when enabled, anchor ingredients are hard-filtered before scoring (spec 15.2). Response: `results` (strong matches) and `overflowResults` (behind "show more"), both re-ranked (7.3) then split by the max-missing threshold (7.4). Matches are tagged core (user-typed ingredient) vs. supporting (spice inventory); supporting matches earn reduced score credit and seasoning-only recipes are dropped.

## Tests

90 tests, no network, no full DB required — pure functions plus the checked-in 50-recipe fixture DB (spec section 8):

```bash
python -m pytest tests/        # from the project root
```

Includes the spec 11.2 regression cases: "chickpeas + vegetarian" returns no meat; "chicken" never matches recipes that merely contain chicken broth. Also includes the V4 spec 15 anchor-matching regressions: chicken never returns pork, strict protein matching excludes extra proteins, and whey protein resolves to the protein-powder family.

Rebuild the fixture DB after schema changes with `python etl/build_fixtures.py`.

## Project layout

```
PantryProject/
├── app/
│   ├── TECHNICAL_NOTES.md     # detailed implementation notes
│   ├── backend/
│   │   ├── app.py             # Flask routes
│   │   ├── recipe_store.py    # local recipe DB access (11.1/11.2/11.3)
│   │   ├── search.py          # pure scoring/ranking (7.3/7.4)
│   │   ├── normalize.py       # ingredient normalization (7.2) + matching rule
│   │   ├── roles.py           # anchor/protein-family hard filters (15)
│   │   ├── nutrition.py       # Tier-1 nutrition payloads (11.4)
│   │   ├── db.py              # user-prefs SQLite (staples/spices/favorites/exclusions)
│   │   └── requirements.txt
│   └── frontend/              # index.html / style.css / app.js
├── etl/                       # spec 10.3 — run once to build data/pantry.db
│   ├── run_all.py             # download + full pipeline
│   ├── load_recipes.py        # step 1 (quantities, servings, nutrition, images)
│   ├── build_ingredient_index.py  # step 2 (the heart of search)
│   ├── derive_diet_flags.py   # step 3
│   ├── build_fixtures.py      # 50-recipe test/demo DB
│   └── common.py              # schema, exclusion keyword sets, field parsers
├── data/
│   ├── fixtures.db            # checked in — app + tests work out of the box
│   └── pantry.db              # built by ETL (gitignored)
└── tests/
    ├── test_pure_functions.py
    ├── test_quantities.py
    ├── test_anchor_matching.py
    └── test_local_db.py
```

## Notes on the spec's open questions

- **Accounts**: none — local-only, per spec 12.1 (resolves section 6).
- **Diet/intolerance filters**: per-search chips. Making them a saved, overridable profile default is a straightforward follow-up (`user_preferences` table + prefill).
- **Dataset licensing** (spec 14): the Kaggle/FDC datasets are for research and personal use — fine for this personal project; revisit if ever productized.
