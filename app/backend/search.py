"""
V3 spec 7.3 / 7.4 / 11.1 — pure scoring and ranking logic (no I/O).

recipe_store.py runs the SQL (inverted-index candidate query, diet/exclusion
anti-joins); everything here is a pure function over plain dicts so it can be
unit-tested with fixtures (spec section 8).

Candidate dict shape (produced by recipe_store.fetch_candidates):
    {
      "id": int, "title": str, "minutes": int|None,
      "avgRating": float|None, "nRatings": int,
      "usedIngredients":   [{"name": str}, ...],   # matched vocabulary names
      "missedIngredients": [{"name": str}, ...],   # recipe ingredients not matched
    }
"""

from normalize import normalize_ingredient, token_set

# Spec 7.3 missing-ingredient weights.
MISSING_WEIGHT_STAPLE = 0.0
MISSING_WEIGHT_SPICE = 0.25
MISSING_WEIGHT_CORE = 1.0

# Used-ingredient weights (symmetric with the missing weights): a match that
# came only from the user's spice inventory / staples must not count like a
# match on an ingredient they actually typed in — otherwise recipes built
# around your seasonings outrank recipes built around your food.
USED_WEIGHT_CORE = 1.0
USED_WEIGHT_SUPPORTING = 0.25

# Spec 7.4 default for the "max missing ingredients" slider (0-4).
DEFAULT_MAX_MISSING = 2

# Spec 7.5 — retrieve more candidates than displayed so re-ranking has room.
DEFAULT_CANDIDATE_COUNT = 200

# Common seasonings treated like spices for weighting even if the user hasn't
# listed them in their spice inventory (spec 7.3 "spice inventory category").
COMMON_SEASONINGS = {
    "allspice", "basil", "bay leaves", "black pepper", "cardamom",
    "cayenne pepper", "chili flakes", "chili powder", "cinnamon", "cloves",
    "coriander", "cumin", "curry powder", "dried parsley", "fennel seeds",
    "five spice powder", "garam masala", "garlic powder", "ginger",
    "italian seasoning", "mustard seeds", "nutmeg", "old bay seasoning",
    "onion powder", "oregano", "paprika", "red pepper flakes", "rosemary",
    "sage", "saffron", "salt", "smoked paprika", "sumac", "thyme",
    "turmeric", "vanilla extract", "za'atar",
}


def _name_in_set(name, normalized_set):
    """Match a missing-ingredient name against a set of normalized names,
    tolerating token order/plurals (e.g. "olive oil" vs "oil, olive")."""
    canonical = normalize_ingredient(name)
    if canonical in normalized_set:
        return True
    tokens = token_set(canonical)
    return any(token_set(s) == tokens for s in normalized_set)


def classify_missing(name, staples, spices):
    """-> "staple" | "spice" | "core" for one missing-ingredient name."""
    if _name_in_set(name, staples):
        return "staple"
    if _name_in_set(name, spices) or normalize_ingredient(name) in COMMON_SEASONINGS:
        return "spice"
    return "core"


def _normalized_set(names):
    return {normalize_ingredient(n) for n in (names or []) if normalize_ingredient(n)}


def weighted_missing(missed_ingredients, spice_inventory=None, staples_whitelist=None):
    """Spec 7.3 — weighted cost of the missing list: 0.0 staple / 0.25 spice / 1.0 core."""
    staples = _normalized_set(staples_whitelist)
    spices = _normalized_set(spice_inventory)
    weights = {
        "staple": MISSING_WEIGHT_STAPLE,
        "spice": MISSING_WEIGHT_SPICE,
        "core": MISSING_WEIGHT_CORE,
    }
    return sum(
        weights[classify_missing(ing.get("name", ""), staples, spices)]
        for ing in (missed_ingredients or [])
    )


def real_missing_count(missed_ingredients, spice_inventory=None, staples_whitelist=None):
    """Count genuine gaps only — neither staples nor spices the user owns.
    Drives the 7.4 filter and the UI's "N missing" badge."""
    staples = _normalized_set(staples_whitelist)
    spices = _normalized_set(spice_inventory)
    return sum(
        1 for ing in (missed_ingredients or [])
        if classify_missing(ing.get("name", ""), staples, spices) == "core"
    )


def visible_missing(missed_ingredients, staples_whitelist=None):
    """Spec 2.2.3 — filter staples out of the missing list shown to the user."""
    staples = _normalized_set(staples_whitelist)
    return [
        ing for ing in (missed_ingredients or [])
        if not _name_in_set(ing.get("name", ""), staples)
    ]


def weighted_used(used_ingredients):
    """Weighted credit for matched ingredients: 1.0 for ingredients the user
    actually entered ("core": True, the default), 0.25 for matches that came
    only from the spice inventory / staples ("core": False)."""
    return sum(
        USED_WEIGHT_CORE if ing.get("core", True) else USED_WEIGHT_SUPPORTING
        for ing in (used_ingredients or [])
    )


def core_used_count(used_ingredients):
    return sum(1 for ing in (used_ingredients or []) if ing.get("core", True))


def match_ratio(recipe, spice_inventory=None, staples_whitelist=None):
    """Spec 7.3 core formula, with weighted used credit:
    weightedUsed / (weightedUsed + weightedMissing) in 0.0..1.0."""
    used = weighted_used(recipe.get("usedIngredients", []))
    penalty = weighted_missing(recipe.get("missedIngredients", []), spice_inventory, staples_whitelist)
    denominator = used + penalty
    return used / denominator if denominator > 0 else 0.0


# ---------------------------------------------------------------------------
# Spec 7.1 — ranking strategies, configurable server-side so the UI sort
# toggle flips between them without a code change.
# ---------------------------------------------------------------------------

def _key_best_match(r):
    ready = r.get("minutes")
    return (
        # Recipes matching none of the user's typed ingredients (seasoning-only
        # hits) always sink below recipes matching their actual food.
        1 if r.get("coreUsedCount", len(r.get("usedIngredients", []))) == 0 else 0,
        -r.get("matchRatio", 0.0),
        -r.get("coreUsedCount", 0),   # user-entered ingredients beat spice matches
        r.get("realMissingCount", 0),
        ready if isinstance(ready, (int, float)) else 10 ** 6,
        -(r.get("avgRating") or 0.0),          # v3 tie-breaker: dataset rating
        -(r.get("nRatings") or 0),
    )


def _key_fewest_missing(r):
    key = _key_best_match(r)
    return (r.get("realMissingCount", 0),) + key


def _key_fastest(r):
    ready = r.get("minutes")
    return (ready if isinstance(ready, (int, float)) else 10 ** 6,) + _key_best_match(r)


RANKING_STRATEGIES = {
    "match": _key_best_match,
    "missing": _key_fewest_missing,
    "fastest": _key_fastest,
}
DEFAULT_RANKING = "match"


def rerank_results(recipes, spice_inventory=None, staples_whitelist=None,
                   strategy=DEFAULT_RANKING):
    """
    Spec 7.3 — score and sort candidates locally. Adds matchRatio,
    realMissingCount and weightedMissing to each recipe; returns a new sorted
    list, input not mutated.
    """
    enriched = []
    for recipe in recipes or []:
        item = dict(recipe)
        item["matchRatio"] = round(match_ratio(item, spice_inventory, staples_whitelist), 4)
        item["realMissingCount"] = real_missing_count(
            item.get("missedIngredients", []), spice_inventory, staples_whitelist)
        item["weightedMissing"] = round(weighted_missing(
            item.get("missedIngredients", []), spice_inventory, staples_whitelist), 4)
        item["coreUsedCount"] = core_used_count(item.get("usedIngredients", []))
        enriched.append(item)

    key = RANKING_STRATEGIES.get(strategy, _key_best_match)
    return sorted(enriched, key=key)


def filter_by_missing_count(recipes, max_missing=DEFAULT_MAX_MISSING,
                            spice_inventory=None, staples_whitelist=None):
    """
    Spec 7.4 — split into (primary, overflow): recipes with more than
    `max_missing` real missing ingredients go behind "show more" rather than
    being dropped, so a sparse pantry still returns something.
    """
    primary, overflow = [], []
    for recipe in recipes or []:
        missing = recipe.get("realMissingCount")
        if missing is None:
            missing = real_missing_count(
                recipe.get("missedIngredients", []), spice_inventory, staples_whitelist)
        (primary if missing <= max_missing else overflow).append(recipe)
    return primary, overflow
