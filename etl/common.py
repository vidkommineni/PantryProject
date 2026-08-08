"""
Shared ETL pieces (spec 10.3 / 10.4): schema DDL, diet-exclusion keyword sets,
%DV -> absolute-unit conversion, and the vocabulary/index builders used both by
the real Food.com pipeline (run_all.py) and the fixtures builder.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
BACKEND_DIR = REPO_ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from normalize import normalize_ingredient, token_set  # noqa: E402

# ---------------------------------------------------------------------------
# Schema (spec 10.4)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    minutes INTEGER,
    n_steps INTEGER,
    steps_json TEXT,
    description TEXT,
    n_ingredients INTEGER,
    raw_ingredients_json TEXT,
    image_url TEXT,
    default_servings INTEGER DEFAULT 1,
    avg_rating REAL,
    n_ratings INTEGER DEFAULT 0,
    calories REAL,
    macros_json TEXT,
    diet_flags INTEGER DEFAULT 0,
    quality_score REAL
);
CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name_canonical TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id INTEGER NOT NULL,
    ingredient_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ri_ingredient ON recipe_ingredients (ingredient_id, recipe_id);
CREATE INDEX IF NOT EXISTS idx_ri_recipe     ON recipe_ingredients (recipe_id, ingredient_id);
CREATE TABLE IF NOT EXISTS ingredient_synonyms (
    alias TEXT NOT NULL,
    ingredient_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_syn_alias ON ingredient_synonyms (alias);
CREATE TABLE IF NOT EXISTS diet_exclusions (
    diet TEXT NOT NULL,
    ingredient_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_de_diet ON diet_exclusions (diet, ingredient_id);
CREATE INDEX IF NOT EXISTS idx_de_ing  ON diet_exclusions (ingredient_id);
CREATE TABLE IF NOT EXISTS recipe_name_exclusions (
    recipe_id INTEGER NOT NULL,
    diet TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rne_diet ON recipe_name_exclusions (diet, recipe_id);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS ingredients_fts
USING fts5(name_canonical, content='ingredients', content_rowid='id');
"""


def create_schema(conn):
    conn.executescript(SCHEMA)
    try:
        conn.executescript(FTS_SCHEMA)
    except Exception:
        pass  # FTS5 unavailable -> autocomplete falls back to LIKE


def rebuild_fts(conn):
    try:
        conn.execute("INSERT INTO ingredients_fts(ingredients_fts) VALUES('rebuild')")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tier-1 nutrition (spec 11.4): the "Recipes and Reviews" dataset ships
# absolute per-serving values (grams / mg), so no %DV conversion is needed.
# ---------------------------------------------------------------------------

MACRO_KEYS = ["fat", "saturated_fat", "sugar", "sodium", "protein", "carbs",
              "fiber", "cholesterol"]


def build_macros(fat, satfat, sugar, sodium, protein, carbs, fiber, cholesterol):
    def num(x):
        try:
            v = float(x)
            return round(v, 1) if v == v else None  # NaN check
        except (TypeError, ValueError):
            return None
    macros = {
        "fat": num(fat), "saturated_fat": num(satfat), "sugar": num(sugar),
        "sodium": num(sodium), "protein": num(protein), "carbs": num(carbs),
        "fiber": num(fiber), "cholesterol": num(cholesterol),
    }
    return {k: v for k, v in macros.items() if v is not None}


# ---------------------------------------------------------------------------
# Dataset field parsing: R-style c("a", "b") vectors and ISO-8601 durations.
# The parquet files store real arrays; the CSVs store R vector literals.
# ---------------------------------------------------------------------------

def parse_r_vector(value):
    """R c("a", "b") string / real list / scalar -> list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None]
    if hasattr(value, "tolist"):  # numpy array from parquet
        return [str(v) for v in value.tolist() if v is not None]
    if isinstance(value, float):  # NaN
        return []
    s = str(value).strip()
    if not s or s.upper() == "NA":
        return []
    if s.startswith("c(") and s.endswith(")"):
        return re.findall(r'"((?:[^"\\]|\\.)*)"', s)
    return [s.strip('"')]


def parse_iso_duration_minutes(value):
    """'PT1H30M' / 'P1DT2H' -> total minutes, or None."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    m = re.match(
        r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?$", str(value).strip())
    if not m or not any(m.groups()):
        return None
    days, hours, mins = (int(g) if g else 0 for g in m.groups())
    return days * 24 * 60 + hours * 60 + mins


# ---------------------------------------------------------------------------
# Diet flags from tags (spec 10.3 step 4)
# ---------------------------------------------------------------------------

DIET_FLAG_BITS = {
    "vegetarian": 1, "vegan": 2, "gluten-free": 4,
    "dairy-free": 8, "low-carb": 16, "paleo": 32,
}

TAG_TO_DIET = {
    "vegetarian": "vegetarian",
    "vegan": "vegan",
    "gluten-free": "gluten-free",
    "gluten free": "gluten-free",
    "lactose": "dairy-free",
    "lactose free": "dairy-free",
    "dairy-free": "dairy-free",
    "dairy free": "dairy-free",
    "low-carb": "low-carb",
    "low carb": "low-carb",
    "paleo": "paleo",
}

# Flag diet -> the diet_exclusions key used for the ingredient-scan-derived
# flags (see derive_diet_flags.py). Keyword coverage varies by dataset, so a
# recipe also earns a flag when its ingredient list is clean for that diet.
FLAG_TO_EXCLUSION_KEY = {
    "vegetarian": "vegetarian",
    "vegan": "vegan",
    "gluten-free": "gluten",
    "dairy-free": "dairy",
    "low-carb": "ketogenic",
    "paleo": "paleo",
}


def diet_flags_from_tags(tags):
    flags = 0
    for tag in tags or []:
        diet = TAG_TO_DIET.get(str(tag).strip().lower())
        if diet:
            flags |= DIET_FLAG_BITS[diet]
    # vegan implies vegetarian + dairy-free
    if flags & DIET_FLAG_BITS["vegan"]:
        flags |= DIET_FLAG_BITS["vegetarian"] | DIET_FLAG_BITS["dairy-free"]
    return flags


# ---------------------------------------------------------------------------
# Exclusion keyword sets (spec 11.2), matched token-wise against the vocabulary
# at ETL time so runtime filtering is a pure indexed anti-join.
# A keyword hits an ingredient when every keyword token appears (singularized)
# in the ingredient's token set — so "chicken" hits "chicken broth" (correct:
# broth is NOT vegetarian) but never "chickpeas".
# ---------------------------------------------------------------------------

MEAT = [
    "chicken", "beef", "pork", "lamb", "bacon", "ham", "turkey", "veal",
    "duck", "goose", "venison", "sausage", "pepperoni", "prosciutto",
    "salami", "chorizo", "meat", "meatball", "steak", "brisket", "ribs",
    "hot dog", "gelatin", "lard", "liver", "oxtail", "pastrami",
]
FISH = [
    "fish", "salmon", "tuna", "anchovy", "anchovies", "cod", "halibut",
    "tilapia", "trout", "sardine", "haddock", "mackerel", "snapper",
    "swordfish", "fish sauce", "worcestershire sauce",
]
SHELLFISH = [
    "shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster",
    "scallop", "squid", "octopus", "crawfish", "oyster sauce",
]
DAIRY = [
    "milk", "butter", "cheese", "cream", "yogurt", "ghee", "paneer",
    "buttermilk", "custard", "ice cream", "sour cream", "whipping cream",
    "heavy cream", "half-and-half", "parmesan", "mozzarella", "cheddar",
    "feta", "ricotta", "mascarpone", "brie", "gouda", "condensed milk",
    "evaporated milk", "whey", "cream cheese",
]
EGG = ["egg", "eggs", "mayonnaise", "meringue"]
GLUTEN = [
    "flour", "wheat", "bread", "breadcrumbs", "pasta", "spaghetti",
    "macaroni", "penne", "fettuccine", "linguine", "lasagna", "couscous",
    "barley", "rye", "semolina", "panko", "seitan", "cracker", "crackers",
    "tortellini", "orzo", "gnocchi", "phyllo", "puff pastry", "pita",
]
PEANUT = ["peanut", "peanuts", "peanut butter", "peanut oil"]
TREE_NUT = [
    "almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut",
    "macadamia", "brazil nut", "pine nut", "chestnut", "nutella",
]
SOY = ["soy", "soybean", "tofu", "edamame", "tempeh", "miso", "soy sauce", "tamari"]
SESAME = ["sesame", "tahini", "sesame oil", "sesame seed"]
SULFITE = ["wine", "dried apricot", "molasses", "sauerkraut", "grape juice"]
HIGH_CARB = [
    "sugar", "flour", "bread", "pasta", "rice", "potato", "potatoes",
    "corn", "honey", "oats", "oatmeal", "tortilla", "maple syrup",
]
LEGUMES_GRAINS_DAIRY = DAIRY + GLUTEN + [
    "rice", "oats", "corn", "beans", "lentils", "chickpeas", "peanut",
    "tofu", "soy", "sugar",
]

# diet/intolerance name -> keyword list. Diet names match the UI chips;
# intolerance names match the intolerance chips.
EXCLUSION_KEYWORDS = {
    "vegetarian": MEAT + FISH + SHELLFISH,
    "vegan": MEAT + FISH + SHELLFISH + DAIRY + EGG + ["honey"],
    "pescetarian": MEAT,
    "ketogenic": HIGH_CARB,
    "paleo": LEGUMES_GRAINS_DAIRY,
    # intolerances (spec 2.1)
    "dairy": DAIRY,
    "egg": EGG,
    "gluten": GLUTEN,
    "wheat": GLUTEN,
    "peanut": PEANUT,
    "tree nut": TREE_NUT,
    "seafood": FISH + SHELLFISH,
    "shellfish": SHELLFISH,
    "soy": SOY,
    "sesame": SESAME,
    "sulfite": SULFITE,
}


def keyword_hits(keyword, ingredient_name):
    """Token-subset match: every keyword token present in the ingredient name."""
    kw_tokens = token_set(keyword)
    return bool(kw_tokens) and kw_tokens <= token_set(ingredient_name)


def build_diet_exclusions(conn):
    """Spec 10.3 step 4 (second half): map keyword sets to vocabulary IDs."""
    conn.execute("DELETE FROM diet_exclusions")
    vocab = conn.execute("SELECT id, name_canonical FROM ingredients").fetchall()
    rows = []
    for diet, keywords in EXCLUSION_KEYWORDS.items():
        for ing_id, name in vocab:
            if any(keyword_hits(kw, name) for kw in keywords):
                rows.append((diet, ing_id))
    conn.executemany("INSERT INTO diet_exclusions (diet, ingredient_id) VALUES (?, ?)", rows)
    return len(rows)


# A recipe's title is a hard-to-fake signal ("Curried Shrimp") that the
# dataset sometimes disagrees with itself about: some rows have their real
# ingredient list truncated/corrupted upstream (the shrimp is in the title
# but not in RecipeIngredientParts), and some carry a self-reported
# "vegetarian"/"vegan" keyword tag that's simply wrong. diet_exclusions (the
# ingredient-based anti-join) can't catch either case, so this is a second,
# independent anti-join over the recipe name.
#
# Skip the name check when the title itself signals an intentional
# meat-free/plant-based version ("Vegetarian Chicken Nuggets", "Mock Duck")
# so we don't punish recipes for using a meat word to describe a substitute.
VEG_SIGNAL_GROUPS = [
    {"vegetarian"}, {"vegan"}, {"veggie"}, {"meatless"}, {"meat", "free"},
    {"plant", "based"}, {"mock"}, {"faux"}, {"fake"}, {"imitation"},
]


def build_name_exclusions(conn):
    """Spec 11.2 follow-up — name-derived anti-join, independent of both the
    ingredient list and the dataset's self-reported diet tags."""
    conn.execute("DELETE FROM recipe_name_exclusions")
    rows = conn.execute("SELECT id, name FROM recipes").fetchall()
    out = []
    for rid, name in rows:
        name_tokens = token_set(name)
        if any(group <= name_tokens for group in VEG_SIGNAL_GROUPS):
            continue
        for diet, keywords in EXCLUSION_KEYWORDS.items():
            if any(keyword_hits(kw, name) for kw in keywords):
                out.append((rid, diet))
    conn.executemany(
        "INSERT INTO recipe_name_exclusions (recipe_id, diet) VALUES (?, ?)", out)
    return len(out)


def build_synonyms(conn):
    """Seed ingredient_synonyms from the normalize.py dictionary, mapped to
    whatever canonical names actually exist in this DB's vocabulary."""
    from normalize import INGREDIENT_SYNONYMS
    conn.execute("DELETE FROM ingredient_synonyms")
    name_to_id = {
        r[1]: r[0]
        for r in conn.execute("SELECT id, name_canonical FROM ingredients").fetchall()
    }
    rows = []
    for alias, canonical in INGREDIENT_SYNONYMS.items():
        ing_id = name_to_id.get(canonical)
        if ing_id:
            rows.append((alias, ing_id))
    conn.executemany("INSERT INTO ingredient_synonyms (alias, ingredient_id) VALUES (?, ?)", rows)
    return len(rows)


def parse_stringified_list(value):
    """Food.com CSVs store Python-list literals as strings; parse defensively."""
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        import ast
        parsed = ast.literal_eval(value)
        return list(parsed) if isinstance(parsed, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return [s for s in re.split(r"[,;]", value.strip("[]")) if s.strip()]


def insert_recipe_ingredients(conn, recipe_id, raw_ingredient_names):
    """Normalize (7.2) each raw name, upsert into the vocabulary, and write the
    inverted index rows. Returns the ingredient IDs used."""
    ids = []
    seen = set()
    for raw in raw_ingredient_names:
        canonical = normalize_ingredient(raw)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        cur = conn.execute(
            "INSERT OR IGNORE INTO ingredients (name_canonical) VALUES (?)", (canonical,))
        row = conn.execute(
            "SELECT id FROM ingredients WHERE name_canonical = ?", (canonical,)).fetchone()
        ids.append(row[0])
    conn.executemany(
        "INSERT INTO recipe_ingredients (recipe_id, ingredient_id) VALUES (?, ?)",
        [(recipe_id, i) for i in ids])
    return ids


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Recipe-quality cleanup: Bayesian-averaged ranking signal + near-duplicate
# collapsing. Both address the same complaint (raw dataset dump surfaces
# junky/near-identical/unreliably-rated recipes ahead of genuinely good ones).
# ---------------------------------------------------------------------------

QUALITY_PRIOR_COUNT = 5  # "votes" of weight given to the dataset-wide average


def apply_quality_scores(conn, prior_count=QUALITY_PRIOR_COUNT):
    """
    Bayesian-average rating (the same shape IMDB's "weighted rating" uses):

        quality_score = (v * R + m * C) / (v + m)

    v = this recipe's n_ratings, R = its avg_rating, C = the dataset-wide
    mean rating (over recipes that have at least one rating), m = prior_count.

    A recipe with one 5-star rating no longer outranks one with hundreds of
    ratings averaging 4.6 — with v=0 the score collapses to C, so unrated
    recipes land at the dataset average rather than at the top or bottom.
    """
    try:
        conn.execute("ALTER TABLE recipes ADD COLUMN quality_score REAL")
    except sqlite3.OperationalError:
        pass  # already has the column

    row = conn.execute(
        "SELECT AVG(avg_rating) FROM recipes WHERE n_ratings > 0 AND avg_rating IS NOT NULL"
    ).fetchone()
    dataset_mean = row[0] if row and row[0] is not None else 4.0

    rows = conn.execute(
        "SELECT id, avg_rating, n_ratings FROM recipes"
    ).fetchall()
    updates = []
    for rid, avg_rating, n_ratings in rows:
        v = n_ratings or 0
        r = avg_rating if avg_rating is not None else 0.0
        score = (v * r + prior_count * dataset_mean) / (v + prior_count)
        updates.append((round(score, 4), rid))
    conn.executemany("UPDATE recipes SET quality_score = ? WHERE id = ?", updates)
    return len(updates)


_TRAILING_TAG_RE = re.compile(r"\s*#\s*\d+\s*$")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")


def _name_stem(name):
    """Collapse numbered variants ("Sourdough Starter #1".."#6") onto one key."""
    stem = _TRAILING_TAG_RE.sub("", (name or "").lower())
    stem = _PUNCT_RE.sub(" ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def dedupe_recipes(conn):
    """
    Collapse near-duplicate recipes: same name stem (ignoring a trailing
    "#N" variant tag) AND the same normalized ingredient set. Keeps whichever
    copy has the most ratings (then the higher quality signal); deletes the
    rest from `recipes`, `recipe_ingredients`, and `_recipe_tags`.

    Must run before build_ingredient_index.py wipes/rebuilds the inverted
    index, since it only needs `recipes.raw_ingredients_json`.
    """
    rows = conn.execute(
        "SELECT id, name, raw_ingredients_json, avg_rating, n_ratings FROM recipes"
    ).fetchall()

    groups = {}
    for rid, name, raw_json, avg_rating, n_ratings in rows:
        try:
            raw = json.loads(raw_json or "[]")
        except (TypeError, ValueError):
            raw = []
        names = frozenset(
            normalize_ingredient(e["name"] if isinstance(e, dict) else e)
            for e in raw
        )
        key = (_name_stem(name), names)
        groups.setdefault(key, []).append(
            (rid, n_ratings or 0, avg_rating or 0.0))

    to_delete = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: (-m[1], -m[2]))
        to_delete.extend(m[0] for m in members[1:])

    if not to_delete:
        return 0

    ph = ",".join("?" * len(to_delete))
    conn.execute(f"DELETE FROM recipes WHERE id IN ({ph})", to_delete)
    conn.execute(f"DELETE FROM _recipe_tags WHERE recipe_id IN ({ph})", to_delete)
    conn.execute(f"DELETE FROM recipe_ingredients WHERE recipe_id IN ({ph})", to_delete)
    return len(to_delete)
