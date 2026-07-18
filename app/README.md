# What's In My Pantry (V1)

An app that takes the ingredients you have on hand and returns recipes you can actually cook. It uses Spoonacular for recipe discovery, instructions, and per-serving nutrition.

V1 is local-storage-only (SQLite file, single user, no accounts) and text-entry only, as specified.

## Stack

- **Backend**: Python + Flask, SQLite for staples/spice inventory/favorites/nutrition cache, and `requests` for Spoonacular API calls.
- **Frontend**: plain HTML/CSS/JS (no build step), served directly by Flask.

## Setup

1. Get API keys:
   - Spoonacular: https://spoonacular.com/food-api (free tier is fine for personal use)

2. Install dependencies:
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Configure keys:
   ```bash
   cp .env.example .env
   # then edit .env and paste in your SPOONACULAR_API_KEY
   ```

4. Run:
   ```bash
   python app.py
   ```
   Open http://localhost:5000

The SQLite database (`backend/pantry.db`) is created automatically on first run, seeded with a default staples whitelist and curated spice list (spec 2.2, 2.3).

## What's implemented (V1 scope)

- Ingredient text box (comma/newline separated) with live autocomplete
- Serving size, time-available, dietary restriction (diet) and intolerance chips
- Staples whitelist: hardcoded defaults + user-editable list; staples are excluded from the "missing ingredients" gap analysis but still shown in full ingredient lists/instructions
- Spice inventory tab: curated spice checklist, persisted, merged into search when "Include my spice inventory" is checked
- Recipe search via `findByIngredients` (simple) or `complexSearch` (when diet/intolerance/time filters are set)
- Recipe detail view with serving-size scaling of ingredient quantities
- Per-serving nutrition from Spoonacular, cached per recipe and requested serving count
- Section 3 extras: missing-ingredients shopping list button, match % badge, sort toggle (best match / fewest missing), favorites, empty-state messaging, nutrition badges in the detail view

## Not yet implemented (spec section 4 — future iterations)

- Image-of-ingredients input
- Receipt scanning / OCR
- Live pantry inventory with auto-depletion after cooking

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/staples` | list staples whitelist |
| POST | `/api/staples` | add a staple |
| DELETE | `/api/staples/<name>` | remove a staple |
| GET | `/api/spices` | curated spice list + owned status |
| POST | `/api/spices/toggle` | mark a spice owned/unowned (or add a custom one) |
| GET | `/api/autocomplete?query=` | ingredient autocomplete |
| POST | `/api/search` | search recipes by ingredients + filters |
| GET | `/api/recipe/<id>?servings=` | full recipe detail, scaled to servings |
| POST | `/api/recipe/<id>/nutrition` | Spoonacular per-serving nutrition |
| GET/POST | `/api/favorites` | list / save a favorite |
| DELETE | `/api/favorites/<id>` | remove a favorite |

## Notes on the spec's open questions

- **Accounts**: none in V1, per the "local-storage-only" recommendation — single SQLite file, no auth.
- **Diet/intolerance filters**: currently per-search only (chips reset each visit). Making them a saved, overridable default (spec's recommendation) is a straightforward follow-up — store them in a `user_preferences` table and prefill the chips on load.
- **API plan tiers / attribution terms**: not addressed in code — review Spoonacular's current terms before any wider use.
