"""
V3 spec 11.4 Tier 1 — nutrition from the dataset's bundled per-recipe values.

The ETL converts Food.com's %-daily-value numbers to absolute units once
(etl/common.py); this module only shapes and scales them for the API. Values
are per serving; totals are per-serving x requested servings (spec 2.6.3).

Tier 2 (USDA FDC per-ingredient computation) is a later phase; when it lands it
plugs in behind the same payload shape with Tier 1 as the fallback.
"""

from normalize import token_set

# ---------------------------------------------------------------------------
# Plausibility guard. The dataset's per-recipe nutrition is self-reported by
# whoever submitted the recipe, and a meaningful slice of it is simply wrong
# (e.g. a "pasta with tomato sauce" recipe listing 1225 kcal / 45g protein
# per serving with no protein-bearing ingredient in sight). Rather than
# silently show numbers we can't stand behind, flag the obviously-broken ones.
# ---------------------------------------------------------------------------

# Ingredient token groups that plausibly explain a meaningful amount of
# protein in a dish. If a recipe reports high protein but none of these
# appear anywhere in its ingredient list, the number is almost certainly bad
# data rather than a real high-protein recipe.
PROTEIN_SOURCE_TOKENS = [
    {"chicken"}, {"beef"}, {"pork"}, {"turkey"}, {"lamb"}, {"duck"}, {"veal"},
    {"bacon"}, {"ham"}, {"sausage"}, {"venison"}, {"fish"}, {"salmon"},
    {"tuna"}, {"cod"}, {"tilapia"}, {"shrimp"}, {"prawn"}, {"crab"},
    {"lobster"}, {"scallop"}, {"egg"}, {"milk"}, {"cheese"}, {"yogurt"},
    {"cream"}, {"tofu"}, {"tempeh"}, {"soy"}, {"edamame"}, {"bean"},
    {"lentil"}, {"chickpea"}, {"quinoa"}, {"nut"}, {"peanut"}, {"almond"},
    {"seitan"}, {"whey"}, {"protein", "powder"},
]

# Per-serving calories above this are implausible for a home recipe; almost
# always a unit-conversion or data-entry error upstream in the dataset.
CALORIE_CEILING = 2200
# Grams of protein that require an identifiable protein-source ingredient to
# be believable.
PROTEIN_FLOOR_WITHOUT_SOURCE = 20


def _has_protein_source(ingredient_names):
    tokens = set()
    for name in ingredient_names or []:
        tokens |= token_set(name)
    return any(group <= tokens for group in PROTEIN_SOURCE_TOKENS)


def plausibility_caveat(per_serving, ingredient_names):
    """None, or a short user-facing caveat when the dataset's per-serving
    nutrition for this recipe looks like bad source data."""
    calories = per_serving.get("calories")
    if calories is not None and calories > CALORIE_CEILING:
        return ("This recipe's calorie count looks unusually high for a single "
                "serving — the source data may be inaccurate.")
    protein = per_serving.get("protein")
    if (protein is not None and protein > PROTEIN_FLOOR_WITHOUT_SOURCE
            and not _has_protein_source(ingredient_names)):
        return ("This recipe's protein estimate looks inconsistent with its "
                "ingredient list — the source data may be inaccurate.")
    return None


UNITS = {
    "calories": "kcal",
    "protein": "g",
    "fat": "g",
    "saturated_fat": "g",
    "carbs": "g",
    "sugar": "g",
    "fiber": "g",
    "sodium": "mg",
    "cholesterol": "mg",
}

HEADLINE = ["calories", "protein", "fat", "carbs"]


def build_payload(per_serving, servings, ingredient_names=None):
    """
    per_serving: {"calories": kcal, "protein": g, ...} (Tier-1 values from the DB)
    -> API payload matching what the frontend renders:
       {calories: {amount, unit}, protein: ..., fat: ..., carbs: ...,
        nutrients: [...], servings, totals: {...}, caveat: str|None}
    """
    servings = max(1, int(servings or 1))
    caveat = plausibility_caveat(per_serving, ingredient_names)

    def entry(key):
        value = per_serving.get(key)
        if value is None:
            return None
        return {"amount": round(float(value), 1), "unit": UNITS.get(key, "")}

    nutrients = []
    totals = {}
    for key in UNITS:
        e = entry(key)
        if e is None:
            continue
        nutrients.append({"name": key.replace("_", " "), **e})
        totals[key] = {"amount": round(e["amount"] * servings, 1), "unit": e["unit"]}

    payload = {key: entry(key) for key in HEADLINE}
    payload.update({
        "nutrients": nutrients,
        "servings": servings,
        "totals": totals,
        "source": "dataset (Tier 1, per serving)",
        "caveat": caveat,
    })
    return payload
