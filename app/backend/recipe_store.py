"""
V3 spec 11.1 / 11.2 / 11.3 — local recipe database access layer.

Reads the SQLite file built by etl/run_all.py (or the checked-in fixtures DB).
All external API calls are gone: search is an inverted-index query over
recipe_ingredients, diet enforcement is an indexed anti-join, autocomplete is
FTS5 over the ingredient vocabulary.

DB resolution order:
  1. $PANTRY_DB (explicit override)
  2. <repo>/data/pantry.db   (full 230K-recipe DB from the ETL)
  3. <repo>/data/fixtures.db (small checked-in DB so the app runs out of the box)
"""

import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from normalize import normalize_ingredient, term_matches_vocab

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"

# Diets whose Food.com tags are reliable enough to require the tag-derived
# flag *in addition to* the exclusion-set scan (spec 11.2 belt-and-suspenders).
# Other diets (keto/paleo/pescetarian) have no trustworthy tag, so they rely on
# the exclusion scan alone.
DIET_FLAG_BITS = {
    "vegetarian": 1,
    "vegan": 2,
    "gluten-free": 4,
    "dairy-free": 8,
    "low-carb": 16,
    "paleo": 32,
}
TAG_ENFORCED_DIETS = {"vegetarian", "vegan"}


class RecipeDbMissingError(RuntimeError):
    pass


def db_path():
    override = os.environ.get("PANTRY_DB")
    if override:
        return Path(override)
    full = DATA_DIR / "pantry.db"
    if full.exists():
        return full
    fixtures = DATA_DIR / "fixtures.db"
    if fixtures.exists():
        return fixtures
    raise RecipeDbMissingError(
        "No recipe database found. Run `python etl/run_all.py` to build "
        "data/pantry.db, or make sure data/fixtures.db exists."
    )


def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Vocabulary + term -> ingredient-ID mapping (spec 7.2 / 11.1)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _vocab():
    """[(id, name_canonical)] — small enough (~15K rows) to keep in memory."""
    with connect() as conn:
        rows = conn.execute("SELECT id, name_canonical FROM ingredients").fetchall()
    return [(r["id"], r["name_canonical"]) for r in rows]


def clear_caches():
    _vocab.cache_clear()


def resolve_term_ids(term):
    """
    Map one normalized user term to matching vocabulary ingredient IDs:
    synonym table first, then the controlled token-matching rule (11.2).
    """
    canonical = normalize_ingredient(term)
    if not canonical:
        return set()

    ids = set()
    with connect() as conn:
        rows = conn.execute(
            "SELECT ingredient_id FROM ingredient_synonyms WHERE alias = ?",
            (canonical,),
        ).fetchall()
    ids.update(r["ingredient_id"] for r in rows)

    for ing_id, name in _vocab():
        if term_matches_vocab(canonical, name):
            ids.add(ing_id)
    return ids


def resolve_terms(terms):
    """{original_term: set(ingredient_ids)} for a list of user terms."""
    return {t: resolve_term_ids(t) for t in terms or []}


# ---------------------------------------------------------------------------
# Search (spec 11.1 + 11.2)
# ---------------------------------------------------------------------------

_INGREDIENT_ANTI_JOIN = (
    "r.id NOT IN (SELECT ri2.recipe_id FROM recipe_ingredients ri2 "
    "JOIN diet_exclusions de ON de.ingredient_id = ri2.ingredient_id "
    "WHERE de.diet = ?)"
)
# Second, independent anti-join over the recipe's own name (spec 11.2
# follow-up). Some dataset rows have a corrupted/truncated ingredient list
# that drops the very ingredient that disqualifies them ("Curried Shrimp"
# with "shrimp" missing from its parsed ingredients) or a bogus self-reported
# "vegetarian" tag; the title still gives it away, so this catches what the
# ingredient-based anti-join and the tag-derived flag both miss.
_NAME_ANTI_JOIN = "r.id NOT IN (SELECT recipe_id FROM recipe_name_exclusions WHERE diet = ?)"


def _diet_clauses(diets, intolerances, params):
    """
    Spec 11.2 — hard filters pushed into the WHERE clause:
      - tag-derived flag bit (for tag-enforced diets), AND
      - indexed anti-join against diet_exclusions for every diet/intolerance, AND
      - indexed anti-join against recipe_name_exclusions (belt-and-suspenders
        against corrupted ingredient rows / bogus self-reported diet tags).
    """
    clauses = []
    for diet in (diets or []):
        diet = diet.strip().lower()
        if not diet:
            continue
        bit = DIET_FLAG_BITS.get(diet)
        if diet in TAG_ENFORCED_DIETS and bit:
            clauses.append(f"(r.diet_flags & {bit}) != 0")
        clauses.append(_INGREDIENT_ANTI_JOIN)
        params.append(diet)
        clauses.append(_NAME_ANTI_JOIN)
        params.append(diet)
    for intol in (intolerances or []):
        intol = intol.strip().lower()
        if not intol:
            continue
        clauses.append(_INGREDIENT_ANTI_JOIN)
        params.append(intol)
        clauses.append(_NAME_ANTI_JOIN)
        params.append(intol)
    return clauses


def fetch_candidates(ingredient_ids, diets=None, intolerances=None,
                     max_minutes=None, excluded_ingredient_ids=None, limit=200):
    """
    Spec 11.1 candidate query over the inverted index, with 11.2 exclusions
    applied *before* scoring (an excluded recipe must never appear).

    Returns candidate dicts (see search.py docstring) with used/missed
    ingredient names resolved.
    """
    ids = sorted(set(ingredient_ids or []))
    if not ids:
        return []

    params = list(ids)
    placeholders = ",".join("?" * len(ids))
    where = []

    if excluded_ingredient_ids:
        excl = sorted(set(excluded_ingredient_ids))
        excl_ph = ",".join("?" * len(excl))
        where.append(
            f"r.id NOT IN (SELECT recipe_id FROM recipe_ingredients "
            f"WHERE ingredient_id IN ({excl_ph}))"
        )
        params.extend(excl)

    where.extend(_diet_clauses(diets, intolerances, params))

    if max_minutes:
        where.append("r.minutes > 0 AND r.minutes <= ?")
        params.append(int(max_minutes))

    where_sql = (" AND " + " AND ".join(where)) if where else ""
    params.append(int(limit))

    sql = f"""
        SELECT r.id, r.name, r.minutes, r.n_ingredients, r.avg_rating, r.n_ratings,
               r.quality_score, r.image_url,
               COUNT(*) AS used_count,
               r.n_ingredients - COUNT(*) AS missing_count
        FROM recipe_ingredients ri
        JOIN recipes r ON r.id = ri.recipe_id
        WHERE ri.ingredient_id IN ({placeholders}){where_sql}
        GROUP BY r.id
        ORDER BY missing_count ASC, used_count DESC,
                 COALESCE(r.quality_score, r.avg_rating, 0) DESC
        LIMIT ?
    """
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        candidates = [dict(r) for r in rows]
        _attach_ingredient_lists(conn, candidates, set(ids))
    return candidates


def _attach_ingredient_lists(conn, candidates, matched_ids):
    """Resolve each candidate's full ingredient list into used/missed names."""
    if not candidates:
        return
    recipe_ids = [c["id"] for c in candidates]
    ph = ",".join("?" * len(recipe_ids))
    rows = conn.execute(
        f"""SELECT ri.recipe_id, ri.ingredient_id, i.name_canonical
            FROM recipe_ingredients ri
            JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id IN ({ph})""",
        recipe_ids,
    ).fetchall()
    by_recipe = {}
    for r in rows:
        by_recipe.setdefault(r["recipe_id"], []).append((r["ingredient_id"], r["name_canonical"]))

    for c in candidates:
        used, missed = [], []
        for ing_id, name in by_recipe.get(c["id"], []):
            (used if ing_id in matched_ids else missed).append(
                {"name": name, "id": ing_id})
        c["title"] = c.pop("name")
        c["avgRating"] = c.pop("avg_rating")
        c["nRatings"] = c.pop("n_ratings")
        # Bayesian-averaged ranking signal (etl/common.py apply_quality_scores);
        # falls back to raw avgRating for DBs built before this column existed.
        c["qualityScore"] = c.pop("quality_score", None)
        if c["qualityScore"] is None:
            c["qualityScore"] = c["avgRating"] or 0.0
        c["imageUrl"] = c.pop("image_url", None)
        c["usedIngredients"] = used
        c["missedIngredients"] = missed
        c.pop("used_count", None)
        c.pop("missing_count", None)


# ---------------------------------------------------------------------------
# Recipe detail + Tier-1 nutrition (spec 11.4)
# ---------------------------------------------------------------------------

def get_recipe(recipe_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row is None:
            return None
        ing_rows = conn.execute(
            """SELECT i.name_canonical FROM recipe_ingredients ri
               JOIN ingredients i ON i.id = ri.ingredient_id
               WHERE ri.recipe_id = ? ORDER BY ri.rowid""",
            (recipe_id,),
        ).fetchall()

    recipe = dict(row)
    recipe["steps"] = json.loads(recipe.pop("steps_json") or "[]")
    recipe["ingredients"] = [r["name_canonical"] for r in ing_rows]
    # Display list with quantities: [{"amount": "1 1/2"|None, "name": ...}].
    # Old DBs stored plain name strings — normalize both shapes.
    display = []
    raw = recipe.pop("raw_ingredients_json", None)
    if raw:
        try:
            for entry in json.loads(raw):
                if isinstance(entry, dict):
                    display.append({"amount": entry.get("amount"),
                                    "name": entry.get("name", "")})
                else:
                    display.append({"amount": None, "name": str(entry)})
        except (TypeError, ValueError):
            display = []
    if not display:
        display = [{"amount": None, "name": n} for n in recipe["ingredients"]]
    recipe["display_ingredients"] = display
    return recipe


def get_nutrition(recipe_id):
    """Tier-1 nutrition: the dataset's per-recipe values, converted to absolute
    units at ETL time and stored in recipes.calories / recipes.macros_json."""
    with connect() as conn:
        row = conn.execute(
            "SELECT calories, macros_json FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
    if row is None:
        return None
    macros = json.loads(row["macros_json"] or "{}")
    return {"calories": row["calories"], **macros}


# ---------------------------------------------------------------------------
# Autocomplete (spec 11.3)
# ---------------------------------------------------------------------------

def autocomplete(query, limit=8):
    """FTS5 prefix query on the vocabulary; LIKE fallback if FTS is absent."""
    q = normalize_ingredient(query)
    if not q:
        return []
    with connect() as conn:
        try:
            match = " ".join(f'"{tok}"*' for tok in q.split(" "))
            rows = conn.execute(
                """SELECT i.name_canonical FROM ingredients_fts f
                   JOIN ingredients i ON i.id = f.rowid
                   WHERE ingredients_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (match, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                """SELECT name_canonical FROM ingredients
                   WHERE name_canonical LIKE ? OR name_canonical LIKE ?
                   ORDER BY LENGTH(name_canonical) LIMIT ?""",
                (q + "%", "% " + q + "%", limit),
            ).fetchall()
    results = [{"name": r["name_canonical"]} for r in rows]
    if results:
        return results
    # Typo fallback (spec 11.3): rapidfuzz if installed, else empty.
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        return []
    names = [name for _, name in _vocab()]
    hits = process.extract(q, names, scorer=fuzz.WRatio, limit=limit, score_cutoff=75)
    return [{"name": h[0]} for h in hits]
