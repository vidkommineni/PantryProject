"""
Spec 10.3 / 12.3 — one-shot ETL: download the Food.com "Recipes and Reviews"
Kaggle dataset and build data/pantry.db. Run once (idempotent — safe to re-run):

    pip install pandas pyarrow kagglehub
    python etl/run_all.py

This dataset (~500K recipes) includes ingredient quantities, serving counts,
absolute per-serving nutrition, aggregated ratings, and image URLs.

Kaggle download needs a (free) Kaggle account; kagglehub picks up credentials
from ~/.kaggle/kaggle.json. If you've already downloaded recipes.parquet (or
recipes.csv) manually, drop it in data/raw/ and the download is skipped.

Phase 4 note: the USDA FDC pipeline (spec 10.3 steps 5-6, Tier-2 nutrition)
is deliberately not part of this run — Tier-1 dataset nutrition works without it.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR  # noqa: E402

import load_recipes            # noqa: E402
import build_ingredient_index  # noqa: E402
import derive_diet_flags       # noqa: E402

RAW_DIR = DATA_DIR / "raw"
KAGGLE_DATASET = "irkaal/foodcom-recipes-and-reviews"
# Ratings come pre-aggregated on the recipes file (AggregatedRating /
# ReviewCount), so reviews.* isn't needed.
WANTED = ["recipes.parquet", "recipes.csv"]


def ensure_dataset():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if any((RAW_DIR / f).exists() for f in WANTED):
        print("Dataset already present in data/raw/ — skipping download.")
        return
    print(f"Downloading {KAGGLE_DATASET} via kagglehub...")
    import kagglehub
    path = Path(kagglehub.dataset_download(KAGGLE_DATASET))
    for name in WANTED:
        found = next(path.rglob(name), None)
        if found is not None:
            shutil.copy2(found, RAW_DIR / name)
            print(f"  copied {name}")
            return
    raise SystemExit(f"No recipes file found in the downloaded dataset at {path}")


def main():
    db_path = DATA_DIR / "pantry.db"
    ensure_dataset()
    print("\n[1/3] Loading recipes...")
    load_recipes.main(db_path)
    print("\n[2/3] Building ingredient vocabulary + inverted index...")
    build_ingredient_index.main(db_path)
    print("\n[3/3] Deriving diet flags + exclusion sets...")
    derive_diet_flags.main(db_path)
    print(f"\nDone. Recipe database ready at {db_path}")
    print("Start the app with:  python app/backend/app.py")


if __name__ == "__main__":
    main()
