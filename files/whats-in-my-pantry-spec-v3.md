# "What's In My Pantry" — Product & Technical Spec (v3)

> **Usage context:** this is a personal, non-commercial project for the builder's own use.

> **Architecture note (v2):** Edamam is **not** used. Spoonacular is the single API for both recipe discovery **and** nutrition, fetched on demand when the user asks for it.

> **Architecture note (v3):** the app moves **fully local** — no external API calls at all. Recipe data comes from the **Food.com Kaggle dataset** (~230K recipes) loaded into SQLite; nutrition comes from the **USDA FoodData Central (FDC)** bulk download. Spoonacular is retired entirely. Part III below is the implementation plan.

---

# Part I — V1 (Sections 1–6)

## 1. Product Summary

An app that takes the ingredients a user has on hand and returns recipes they can actually cook. This version uses a **single-API architecture**:
- **Spoonacular** for recipe discovery, ingredient matching, full step-by-step cooking instructions, **and** nutrition information — nutrition is fetched on demand only when the user asks for it (see 2.6).

V1 uses text-entry input; later versions add image/receipt scanning and a live inventory that depletes as recipes are cooked.

> **Why single-API works cleanly:** everything keys off the same Spoonacular recipe ID — discovery, instructions, and nutrition — so there's no cross-vendor ID reconciliation, one set of credentials, and one quota to manage. The trade-off is that Spoonacular's nutrition is tied to the recipe's default serving definition rather than computed from an arbitrary scaled ingredient list; per-serving values are simply multiplied by the user's chosen serving count (see 2.6).

---

## 2. V1 Feature Set

### 2.1 Input UI
- **Ingredient text box**: free-text, comma-or-newline separated, with autocomplete suggestions.
- **Serving size**: numeric stepper (e.g. 1–12).
- **Time available**: dropdown or slider → maps to a max-ready-time filter.
- **Dietary restrictions**: multi-select chips for diet (vegetarian, vegan, ketogenic, paleo, etc.) and intolerances (dairy, egg, gluten, peanut, seafood, sesame, shellfish, soy, sulfite, tree nut, wheat) — keep these as two separate UI groups since they're two separate concepts.
- **Spice/pantry tab** (see 2.3): a separate persistent section, not part of the per-search text box.

### 2.2 "Don't fail on staples" logic
1. Maintain a hardcoded **staples whitelist**: salt, pepper, oil, olive oil, water, sugar, etc.
2. Search with only the user's actual entered ingredients (don't inject staples into the query — it would skew ranking toward trivial matches).
3. Filter the results' missing-ingredients list against the staples whitelist before showing gaps to the user — show only real gaps.
4. Let users edit their own staples whitelist.

### 2.3 Spice inventory tab
- A dedicated tab where the user checks off spices they own from a curated list, stored persistently.
- At search time, merge `searchIngredients = mainTextBoxIngredients + userSpiceInventory` before searching.
- Maintain your own curated spice list — no data source exposes a reliable "spice" category flag.

### 2.4 Always show basic spices in output
- Even though staples are excluded from *matching* logic, display the full real ingredient list and instructions to the user — they still need to know to add salt when cooking.

### 2.5 Recipe results, instructions, and serving scaling
- Return a ranked list with used/missing ingredient counts and images (where available).
- Apply diet + intolerance + max-ready-time filters together in one query when set.
- Full instructions, ready time, and default servings load when the user opens a recipe.
- **Serving size scaling**: scale ingredient quantities client-side by `desiredServings / defaultServings`.

### 2.6 Nutrition on demand
Nutrition is a distinct, user-initiated step — it is **not** fetched/computed during search or shown by default:

1. When the user asks for nutrition (taps a "Nutrition" button/tab on an opened recipe), compute/fetch it for that recipe only.
2. Display calories, macros, and available micronutrients alongside the recipe.
3. **Serving-size scaling**: nutrition is per serving of the recipe's default serving definition; multiply by the user's chosen serving count for totals.
4. **Never bundle nutrition into search/list queries** — most recipes in a result grid are never opened.
5. **Caching**: store computed nutrition per recipe id (`RecipeNutritionCache`, section 5) so re-opening a recipe never recomputes.

---

## 3. Suggested Additions for V1 (small lift, real value)

- **"Missing ingredients" shopping-list button**, built from the filtered missing-ingredients list.
- **Match percentage badge** on each recipe card ("You have 8/10 ingredients").
- **Sort/filter toggle**: fewest missing ingredients / fastest / best match.
- **Save/favorite recipes** — simple local list.
- **Empty/near-empty state handling** with a fallback suggestion (broaden filters, add a spice) rather than a blank screen.
- **Nutrition summary badges** (calories, protein) directly on the recipe card once the on-demand nutrition fetch (2.6) has run for a recipe.

---

## 4. Future Iterations

### 4.1 Additional input methods
- **Image of ingredients**: "identify everything in this fridge photo" is its own technical track — likely a general vision model, independent of the recipe data layer.
- **Receipt scanning**: OCR → parse line items → fuzzy-match parsed strings against the local ingredient vocabulary to normalize names.
- **Text entry**: already in V1.

### 4.2 Live inventory with auto-depletion
- Persistent **pantry table** (ingredient, quantity, unit, expiration date) in your own database.
- On recipe confirmation, pull the recipe's scaled ingredient list (2.5) and subtract from the pantry table.
- Unit conversion (recipe "2 tbsp" vs. pantry "500 ml") is the hard part — use a dedicated conversion utility rather than hand-rolling it.
- Prefer an editable "about to subtract this — adjust if needed" confirmation step over silent auto-depletion.
- Depletion reuses the same scaled ingredient list built in 2.5 for display.

---

## 5. Data Model Sketch

```
User
 - id, name, dietary_preferences[], intolerances[]

PantryItem (future: live inventory)
 - id, user_id, ingredient_name, quantity, unit, expiration_date

SpiceInventory
 - id, user_id, spice_name

SavedRecipe
 - id, user_id, recipe_id, saved_at

RecipeNutritionCache
 - id, recipe_id, calories_per_serving, macros_json, computed_at
   (cache key = recipe id; nutrition is per-serving, serving totals are
    derived by multiplication)

StaplesWhitelist
 - id, user_id (nullable = global default), ingredient_name
```

---

## 6. Open Questions to Resolve Before Building
- Account system from day one, or local-storage-only for V1?
- Do diet/intolerance filters apply per-search or as a saved, overridable user profile default? (Recommend: saved default, overridable per search.)

---

# Part II — V2: Recipe Match Quality (Sections 7–8)

> **Context:** after the initial build, recipe results didn't prioritize the
> user's entered ingredients well (recipes with many missing ingredients ranked
> near the top). Backend language: **Python**. The Spoonacular quota-strategy
> material from the original v2 addendum is dropped in v3 — with a local
> database there is no quota. The match-quality logic below carries forward
> unchanged because it is pure local logic.

## 7. Recipe Match Quality

### 7.1 Ranking strategy
- Default ranking: **minimize missing ingredients** (recipes you can actually cook rank first).
- Keep the ranking strategy configurable server-side so the "Sort by" UI toggle (best match / fewest missing / fastest) can flip between strategies without a code change.

### 7.2 Ingredient normalization layer (pre-query)
Matching is literal; "whey chocolate protein powder" may not hit recipes indexed under "protein powder."

- Normalize each user-entered ingredient before querying:
  1. Lowercase, trim, collapse whitespace.
  2. Strip brand-ish / descriptor tokens ("whey", "organic", "fresh", "boneless").
  3. Map through a small **synonym dictionary** to canonical ingredient names.
- In v3, build the canonical vocabulary from the dataset itself: the distinct tokenized ingredient names across all recipes (see 10.3).
- Keep the *original* user string for display; use the *normalized* string only for matching.

### 7.3 Client-side re-ranking
- Retrieve more candidates than displayed (e.g. 30+), then score:

  ```
  score = usedIngredientCount / (usedIngredientCount + weightedMissing)
  weightedMissing = sum over missing ingredients of:
      0.0  if ingredient is in staples whitelist (2.2 list)
      0.25 if ingredient is in the user's spice inventory category
      1.0  otherwise
  ```

- A recipe missing only salt/oil/a spice ranks as effectively a full match.
- Tie-breakers: fewer real missing ingredients, then shorter ready time, then higher dataset rating (v3 bonus — see 10.2).

### 7.4 Hard filter on missing count
- Drop (or collapse behind a "show more" section) any recipe with more than 2 missing ingredients **after** staple/spice filtering.
- Optionally expose this as a "max missing ingredients" slider (0–4) in the UI.

### 7.5 Two-step fetch (candidates → detail)
- Step 1: candidate list query (counts + summary only).
- Step 2: full detail (instructions, nutrition) loaded only for recipes the user opens.
- Still worth keeping locally — it keeps list queries fast against 230K rows.

## 8. Testing strategy (carried from v2, simplified)
- Ranking, staple filtering, normalization (7.2), re-ranking (7.3), scaling (2.5), and match-percentage display are **pure functions** — unit test them with fixture JSON in → expected output.
- With a local database there are no live-API integration tests; instead, test against a small fixture SQLite DB (~50 hand-picked recipes) checked into the repo.

---

# Part III — V3: Fully Local Architecture (Kaggle + USDA FDC)

> **Goal:** run the entire app on your own machine with zero external API calls,
> no quotas, no keys, no attribution obligations. Everything below is the
> recommended implementation plan.

## 10. Data Layer

### 10.1 Sources (one-time downloads)
| Data | Source | Size | What you get |
|---|---|---|---|
| Recipes | Kaggle: **"Food.com Recipes and Interactions"** (`shuyangli94/food-com-recipes-and-user-interactions`) — `RAW_recipes.csv`, `RAW_interactions.csv` | ~500 MB raw | ~230K recipes: name, minutes, tags, per-recipe nutrition, steps, description, tokenized ingredients; ~1.1M ratings/reviews |
| Nutrition | **USDA FoodData Central** bulk CSV (fdc.nal.usda.gov/download-datasets) — use the **"SR Legacy"** and/or **"Foundation Foods"** sets | ~200 MB | Foods, nutrient values per 100g, and portion weights ("1 cup = 158g") |

Download via `kagglehub` (or the Kaggle CLI) and plain HTTPS for FDC — these are file downloads, not runtime API dependencies.

### 10.2 Why Food.com over RecipeNLG
`minutes` maps directly to the time filter; `tags` pre-derive most diet/intolerance filters; bundled per-recipe nutrition means the nutrition feature works before the FDC pipeline exists; ratings give a quality/ranking signal. RecipeNLG (2M recipes) is raw text only — keep it as an optional later bulk-add behind the same index interface.

### 10.3 ETL pipeline (`etl/` — run once, idempotent)
1. `load_recipes.py`: read `RAW_recipes.csv` → clean (drop null-instruction rows, parse the stringified Python lists in `ingredients`, `steps`, `tags`, `nutrition`) → write `recipes` table.
2. `load_ratings.py`: aggregate `RAW_interactions.csv` → `avg_rating`, `n_ratings` per recipe → join into `recipes`.
3. `build_ingredient_index.py`: extract distinct ingredient strings → normalize (7.2 rules) → write `ingredients` vocabulary table + `recipe_ingredients(recipe_id, ingredient_id)` **inverted index**. This is the heart of search.
4. `derive_diet_flags.py`: map Food.com tags → your filter chips (`vegetarian`, `vegan`, `gluten-free`, `dairy-free`, `30-minutes-or-less`, ...). For intolerances not covered by tags, derive from ingredients (recipe contains "milk|butter|cheese" → not dairy-free). Store as boolean columns or a flags bitmask. Also build the `diet_exclusions` keyword-set table used by the hard enforcement rule (11.2).
5. `load_fdc.py`: load FDC `food.csv`, `nutrient.csv`, `food_nutrient.csv`, `food_portion.csv` into an `fdc` schema; keep only the ~30 nutrients you'll display.
6. `map_ingredients_to_fdc.py`: for each vocabulary ingredient, find the best FDC food via `rapidfuzz` token-set matching; store `ingredient_id → fdc_id, confidence`. Review the top-200 most-used ingredients by hand (they cover the vast majority of recipe lines).

### 10.4 SQLite schema (extends section 5)
```
recipes            (id, name, minutes, n_steps, steps_json, description,
                    default_servings, avg_rating, n_ratings, calories, macros_json,
                    diet_flags)
ingredients        (id, name_canonical, fdc_id NULL, fdc_confidence)
recipe_ingredients (recipe_id, ingredient_id)          -- inverted index, both indexed
ingredient_synonyms(alias, ingredient_id)              -- normalization dictionary
diet_exclusions    (diet, ingredient_id)               -- 11.2 hard-filter keyword sets
user_excluded_ingredients(user_id, ingredient_id)      -- 11.2 "never show me X"
fdc_food / fdc_nutrient_value / fdc_portion            -- trimmed USDA tables
```
SQLite is the right call: single file, zero setup, `recipe_ingredients` with proper indexes answers pantry queries over 230K recipes in milliseconds. Add SQLite **FTS5** on `ingredients.name_canonical` for the autocomplete box.

## 11. Matching & Nutrition Engines

### 11.1 Search (replaces `findByIngredients`)
```sql
SELECT r.id,
       COUNT(*) AS used_count,
       r.n_ingredients - COUNT(*) AS missing_count
FROM recipe_ingredients ri
JOIN recipes r ON r.id = ri.recipe_id
WHERE ri.ingredient_id IN (:normalized_user_ingredient_ids)
GROUP BY r.id
```
Then apply, in Python: staple/spice weighting → 7.3 scoring → 7.4 hard filter → diet/time SQL filters (pushed into the WHERE clause). Fetch top 30, render top N.

### 11.2 Hard diet enforcement & exclusions
Motivated by observed V2 failures (vegetarian searches returning chicken/pork;
"chickpeas" fuzzy-matching "chicken"). Exact ingredient-ID matching (11.1)
already eliminates the substring confusion; this section makes diet filters
impossible to leak past:

- **Belt-and-suspenders diet filtering**: a recipe passes a diet filter only if
  **both** checks pass:
  1. Its tag-derived `diet_flags` (10.3 step 4) include the diet, **and**
  2. An ingredient scan finds nothing from that diet's **exclusion keyword set**
     (e.g. vegetarian: chicken, beef, pork, lamb, bacon, ham, turkey, shrimp,
     fish, anchovy, gelatin, lard, ...).
  Rationale: dataset tags are user-supplied and imperfect; the ingredient scan
  catches mistagged recipes.
- Maintain the exclusion sets as data (`diet_exclusions(diet, ingredient_id)`),
  mapped to vocabulary IDs at ETL time — so the scan is an indexed anti-join,
  not runtime string matching:

  ```sql
  AND r.id NOT IN (
      SELECT ri.recipe_id FROM recipe_ingredients ri
      JOIN diet_exclusions de ON de.ingredient_id = ri.ingredient_id
      WHERE de.diet = :active_diet)
  ```

- **"Never show me X" user setting**: a per-user excluded-ingredients list
  (`UserExcludedIngredient(user_id, ingredient_id)`) applied with the same
  anti-join on every search regardless of diet chips — covers dislikes and
  allergies beyond the standard intolerance list.
- Exclusions are **hard filters applied before scoring** (7.3) — an excluded
  recipe must never appear, regardless of match score.
- Test cases (add to the 8 fixture suite): "chickpeas + vegetarian" returns no
  meat recipes; "chicken" returns no shrimp/lamb/pork recipes that merely
  contain chicken broth — broth matches only if the user entered it or it's a
  staple.

### 11.3 Autocomplete (replaces the autocomplete endpoint)
FTS5 prefix query on the vocabulary table; fall back to `rapidfuzz.process.extract` for typos.

### 11.4 Nutrition (replaces API nutrition; implements 2.6)
Two tiers:
- **Tier 1 (day one):** serve the dataset's bundled per-recipe nutrition (calories, fat, sugar, sodium, protein, sat-fat, carbs — stored as % daily value; convert to absolute units once in ETL).
- **Tier 2 (FDC pipeline):** on request, parse each ingredient line with the `ingredient-parser-nlp` package → (quantity, unit, food) → resolve food via the 10.3(6) mapping → convert quantity to grams using `food_portion` + a `pint`-based unit table → sum nutrient×grams/100 across lines → divide by servings. Falls back to Tier 1 per-line when parsing or mapping fails (the 2.6 graceful-degradation rule).
- Cache results in `RecipeNutritionCache` keyed `(recipe_id, "tier2")`.

## 12. App Architecture & Running Locally

### 12.1 Stack
- **Backend:** Python + **FastAPI** (async, auto-docs at `/docs`, trivial to run locally). Endpoints: `GET /search`, `GET /recipes/{id}`, `GET /recipes/{id}/nutrition`, `GET /autocomplete`, CRUD for staples/spices/saved.
- **Frontend:** start with **Jinja2 templates + htmx** served by the same FastAPI app (one process, no build step). Swap to React later only if the UI outgrows it.
- **State:** everything in the one SQLite file; user prefs (staples, spices, saved recipes) are just tables — no accounts needed (resolves the section 6 question: local-only).

### 12.2 Repo layout
```
pantry/
  etl/            # 10.3 scripts (run once)
  app/
    main.py       # FastAPI app + routes
    search.py     # 11.1 query + 7.3 scoring (pure functions)
    normalize.py  # 7.2
    nutrition.py  # 11.3
    templates/    # Jinja2 + htmx UI
  data/
    pantry.db     # built by ETL (gitignored)
    fixtures.db   # 50-recipe test DB (checked in)
  tests/
```

### 12.3 Run instructions
```bash
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn jinja2 rapidfuzz pandas ingredient-parser-nlp pint kagglehub
python etl/run_all.py          # downloads datasets, builds data/pantry.db (~10 min, once)
uvicorn app.main:app --reload  # → http://localhost:8000
```

## 13. Phased Next Steps

- **Phase 0 — Data spike (1–2 evenings):** download both datasets; in a notebook, load `RAW_recipes.csv`, inspect ingredient token quality, and hand-run one pantry query with pandas. Confirms the data before any app code. ✅ *exit: you can list 10 recipes matching ["chicken", "rice", "onion"]*
- **Phase 1 — ETL + search core:** scripts 10.3(1–4), schema 10.4, `search.py` + `normalize.py` as pure functions with unit tests against `fixtures.db`. ✅ *exit: CLI script takes ingredients, prints ranked recipes with match %*
- **Phase 2 — App shell:** FastAPI routes + htmx UI: search page (2.1 controls), results grid with match badges (section 3), recipe detail with serving scaling (2.5), staples & spice tabs (2.2/2.3). Tier-1 nutrition on the detail page. ✅ *exit: usable app in the browser*
- **Phase 3 — Match quality polish:** synonym dictionary buildout, 7.3 weighting with your real staples/spice lists, 7.4 slider, hard diet enforcement + "never show me X" setting (11.2) with its regression tests, sort toggle, shopping-list button, saved recipes.
- **Phase 4 — FDC nutrition (Tier 2):** ETL 10.3(5–6), `nutrition.py`, per-line fallback, nutrition cache. This is the most fiddly phase — do it after the app is already useful.
- **Phase 5 — v1-spec future items:** live inventory with auto-depletion (4.2) — now easier since recipes and pantry share one local DB; receipt OCR; fridge-photo vision (needs a local vision model, e.g. Ollama + a VLM, to stay API-free).

## 14. Feature Modifications vs. the v2 Spec

- **Dropped entirely:** all quota strategy (old sections 8.1–8.5), API caching (`requests-cache`), `MOCK_API` mode, API keys — a local DB *is* the cache and the mock.
- **Changed:** autocomplete now local FTS5; synonym dictionary seeded from the dataset vocabulary instead of an autocomplete endpoint; nutrition becomes two-tier (bundled → FDC); attribution/plan-tier open questions (section 6) are gone. Note the datasets are scraped/aggregated for research and personal use — fine here, revisit if ever productized.
- **Gained:** ratings as a ranking signal (7.3 tie-breaker), offline operation, unlimited dev iteration, and full ownership of the matching logic.
- **Lost (accept or mitigate):** recipe images (mitigate: text-first cards, or lazy-load images from recipe URLs where present); Spoonacular's curated ontology (mitigate: tag-derived flags, 10.3(4)); recipe freshness (dataset is static — fine for a personal pantry app).
