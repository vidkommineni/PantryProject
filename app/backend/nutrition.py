"""
V3 spec 11.4 Tier 1 — nutrition from the dataset's bundled per-recipe values.

The ETL converts Food.com's %-daily-value numbers to absolute units once
(etl/common.py); this module only shapes and scales them for the API. Values
are per serving; totals are per-serving x requested servings (spec 2.6.3).

Tier 2 (USDA FDC per-ingredient computation) is a later phase; when it lands it
plugs in behind the same payload shape with Tier 1 as the fallback.
"""

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


def build_payload(per_serving, servings):
    """
    per_serving: {"calories": kcal, "protein": g, ...} (Tier-1 values from the DB)
    -> API payload matching what the frontend renders:
       {calories: {amount, unit}, protein: ..., fat: ..., carbs: ...,
        nutrients: [...], servings, totals: {...}}
    """
    servings = max(1, int(servings or 1))

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
    })
    return payload
