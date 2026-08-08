"""
Spec 10.3 step 3 — the heart of search: build the ingredient vocabulary +
recipe_ingredients inverted index from each recipe's raw ingredient list
(stored by load_recipes.py), then seed the synonym table and the FTS5
autocomplete index. Idempotent.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, build_synonyms, rebuild_fts  # noqa: E402
from common import insert_recipe_ingredients  # noqa: E402


def main(db_path=None):
    db_path = Path(db_path or DATA_DIR / "pantry.db")
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM recipe_ingredients")
    conn.execute("DELETE FROM ingredients")
    conn.commit()

    rows = conn.execute("SELECT id, raw_ingredients_json FROM recipes").fetchall()
    for i, (recipe_id, raw_json) in enumerate(rows):
        raw = json.loads(raw_json or "[]")
        # Entries are {"amount", "name"} dicts (or plain strings in old DBs).
        names = [e["name"] if isinstance(e, dict) else e for e in raw]
        insert_recipe_ingredients(conn, recipe_id, names)
        if i % 5000 == 0:
            conn.commit()
            print(f"  indexed {i}/{len(rows)} recipes...", end="\r")
    conn.commit()

    # Normalization dedupes ingredient lines, so re-sync n_ingredients with the
    # indexed count — the 11.1 query does `n_ingredients - COUNT(*)` arithmetic.
    conn.execute("""UPDATE recipes SET n_ingredients =
                    (SELECT COUNT(*) FROM recipe_ingredients
                     WHERE recipe_id = recipes.id)""")
    conn.commit()

    n_vocab = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
    n_syn = build_synonyms(conn)
    rebuild_fts(conn)
    conn.commit()
    conn.close()
    print(f"\nbuild_ingredient_index: {n_vocab} vocabulary entries, {n_syn} synonyms")


if __name__ == "__main__":
    main(*sys.argv[1:])
