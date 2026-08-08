"""
Spec 10.3 step 4 — diet flags + the diet_exclusions table for the 11.2
hard-enforcement anti-join.

A recipe earns a diet flag when EITHER:
  - its dataset keywords/category map to the diet (TAG_TO_DIET), OR
  - its ingredient list contains nothing from that diet's exclusion set
    (keyword coverage varies by dataset, so the ingredient scan is the
    dependable signal; the runtime anti-join remains the hard gate).

Requires load_recipes.py and build_ingredient_index.py to have run. Idempotent.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    DATA_DIR, DIET_FLAG_BITS, FLAG_TO_EXCLUSION_KEY,
    build_diet_exclusions, diet_flags_from_tags, build_name_exclusions,
)


def main(db_path=None):
    db_path = Path(db_path or DATA_DIR / "pantry.db")
    conn = sqlite3.connect(db_path)

    n_excl = build_diet_exclusions(conn)
    n_name_excl = build_name_exclusions(conn)

    # 1. Keyword-derived flags.
    flags_by_recipe = {}
    for recipe_id, tags_json in conn.execute(
            "SELECT recipe_id, tags_json FROM _recipe_tags").fetchall():
        flags = diet_flags_from_tags(json.loads(tags_json or "[]"))
        if flags:
            flags_by_recipe[recipe_id] = flags

    # 2. Ingredient-scan-derived flags: clean for the diet -> flag set.
    for diet, bit in DIET_FLAG_BITS.items():
        excl_key = FLAG_TO_EXCLUSION_KEY.get(diet)
        if not excl_key:
            continue
        clean_ids = [r[0] for r in conn.execute(
            """SELECT r.id FROM recipes r
               WHERE r.id NOT IN (
                   SELECT ri.recipe_id FROM recipe_ingredients ri
                   JOIN diet_exclusions de ON de.ingredient_id = ri.ingredient_id
                   WHERE de.diet = ?)""",
            (excl_key,)).fetchall()]
        for rid in clean_ids:
            flags_by_recipe[rid] = flags_by_recipe.get(rid, 0) | bit

    conn.execute("UPDATE recipes SET diet_flags = 0")
    conn.executemany("UPDATE recipes SET diet_flags = ? WHERE id = ?",
                     [(f, rid) for rid, f in flags_by_recipe.items()])
    conn.commit()
    conn.close()
    print(f"derive_diet_flags: flags on {len(flags_by_recipe)} recipes, "
          f"{n_excl} diet-exclusion rows, {n_name_excl} name-exclusion rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
