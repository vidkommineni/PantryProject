"""
Spec 10.3 step 1 — load the Kaggle "Food.com Recipes and Reviews" dataset
(irkaal/foodcom-recipes-and-reviews) into the recipes table.

Why this dataset (v3.1): unlike RAW_recipes.csv it includes ingredient
QUANTITIES, real serving counts, absolute per-serving nutrition, aggregated
ratings, and image URLs — which restores spec 2.5 serving scaling and gives
the UI real amounts.

Prefers recipes.parquet (fast, typed arrays; needs pyarrow) and falls back to
recipes.csv (R-style c(...) vector strings). Idempotent: wipes and reloads.

Stashes Keywords + RecipeCategory per recipe in _recipe_tags for
derive_diet_flags.py.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    DATA_DIR, create_schema, build_macros, parse_r_vector,
    parse_iso_duration_minutes, dumps,
)

CHUNK = 5000

COLUMNS = [
    "RecipeId", "Name", "TotalTime", "PrepTime", "Description", "Images",
    "RecipeCategory", "Keywords", "RecipeIngredientQuantities",
    "RecipeIngredientParts", "AggregatedRating", "ReviewCount",
    "Calories", "FatContent", "SaturatedFatContent", "CholesterolContent",
    "SodiumContent", "CarbohydrateContent", "FiberContent", "SugarContent",
    "ProteinContent", "RecipeServings", "RecipeInstructions",
]


def _num(value):
    try:
        v = float(value)
        return v if v == v else None  # NaN
    except (TypeError, ValueError):
        return None


def _iter_frames(recipes_path):
    import pandas as pd

    if recipes_path.suffix == ".parquet":
        df = pd.read_parquet(recipes_path)
        cols = [c for c in COLUMNS if c in df.columns]
        df = df[cols]
        for start in range(0, len(df), CHUNK):
            yield df.iloc[start:start + CHUNK]
    else:
        usecols = lambda c: c in COLUMNS  # noqa: E731
        yield from pd.read_csv(recipes_path, chunksize=CHUNK, usecols=usecols)


def _row_get(rec, name):
    return getattr(rec, name, None)


def main(db_path=None, recipes_path=None):
    db_path = Path(db_path or DATA_DIR / "pantry.db")
    if recipes_path is None:
        parquet = DATA_DIR / "raw" / "recipes.parquet"
        csv = DATA_DIR / "raw" / "recipes.csv"
        recipes_path = parquet if parquet.exists() else csv
    recipes_path = Path(recipes_path)
    if not recipes_path.exists():
        raise SystemExit(f"Missing {recipes_path} — run run_all.py to download it.")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS _recipe_tags (
                        recipe_id INTEGER PRIMARY KEY, tags_json TEXT)""")
    conn.execute("DELETE FROM recipes")
    conn.execute("DELETE FROM _recipe_tags")
    conn.commit()

    total = kept = 0
    for chunk in _iter_frames(recipes_path):
        recipe_rows, tag_rows = [], []
        for rec in chunk.itertuples(index=False):
            total += 1
            steps = [s for s in parse_r_vector(_row_get(rec, "RecipeInstructions"))
                     if s and s.upper() != "NA"]
            parts = parse_r_vector(_row_get(rec, "RecipeIngredientParts"))
            if not steps or not parts:
                continue
            quantities = parse_r_vector(_row_get(rec, "RecipeIngredientQuantities"))
            display = []
            for i, name in enumerate(parts):
                qty = quantities[i] if i < len(quantities) else None
                if qty is not None and str(qty).strip().upper() in {"", "NA"}:
                    qty = None
                display.append({"amount": qty, "name": name})

            minutes = (parse_iso_duration_minutes(_row_get(rec, "TotalTime"))
                       or parse_iso_duration_minutes(_row_get(rec, "PrepTime")))
            desc = _row_get(rec, "Description")
            desc = desc if isinstance(desc, str) else ""
            images = parse_r_vector(_row_get(rec, "Images"))
            image_url = next((u for u in images if str(u).startswith("http")), None)
            servings = _num(_row_get(rec, "RecipeServings"))
            servings = int(servings) if servings and servings > 0 else 1

            keywords = parse_r_vector(_row_get(rec, "Keywords"))
            category = _row_get(rec, "RecipeCategory")
            if isinstance(category, str) and category:
                keywords.append(category)

            calories = _num(_row_get(rec, "Calories"))
            macros = build_macros(
                _row_get(rec, "FatContent"), _row_get(rec, "SaturatedFatContent"),
                _row_get(rec, "SugarContent"), _row_get(rec, "SodiumContent"),
                _row_get(rec, "ProteinContent"), _row_get(rec, "CarbohydrateContent"),
                _row_get(rec, "FiberContent"), _row_get(rec, "CholesterolContent"),
            )

            rid = int(_row_get(rec, "RecipeId"))
            recipe_rows.append((
                rid, str(_row_get(rec, "Name")), minutes, len(steps), dumps(steps),
                desc, len(parts), dumps(display), image_url, servings,
                _num(_row_get(rec, "AggregatedRating")),
                int(_num(_row_get(rec, "ReviewCount")) or 0),
                round(calories, 1) if calories is not None else None, dumps(macros),
            ))
            tag_rows.append((rid, dumps(keywords)))
            kept += 1
        conn.executemany(
            """INSERT OR REPLACE INTO recipes
               (id, name, minutes, n_steps, steps_json, description,
                n_ingredients, raw_ingredients_json, image_url, default_servings,
                avg_rating, n_ratings, calories, macros_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            recipe_rows)
        conn.executemany(
            "INSERT OR REPLACE INTO _recipe_tags (recipe_id, tags_json) VALUES (?,?)",
            tag_rows)
        conn.commit()
        print(f"  loaded {kept}/{total} recipes...", end="\r")

    conn.close()
    print(f"\nload_recipes: kept {kept} of {total} rows -> {db_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
