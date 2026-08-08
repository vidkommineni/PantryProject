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
