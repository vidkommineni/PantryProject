"""
Core Spoonacular API integration for the pantry app.

Flow:
  1. search_recipes_by_ingredients() / search_recipes_complex()
                                       -> Spoonacular findByIngredients / complexSearch
  2. get_recipe_information()         -> Spoonacular recipes/{id}/information
  3. scale_ingredients()              -> client-side serving-size scaling
  4. filter_staples()                 -> hide staples from "missing ingredients" display
  5. get_recipe_nutrition()           -> Spoonacular recipe information with nutrition

Requires: pip install requests
Set these environment variables before running:
  SPOONACULAR_API_KEY
"""

import os
import re
import requests

SPOONACULAR_API_KEY = os.environ.get("SPOONACULAR_API_KEY")

SPOONACULAR_BASE = "https://api.spoonacular.com"

# Ingredients that shouldn't block a match or clutter the "missing ingredients" list.
DEFAULT_STAPLES_WHITELIST = {
    "salt", "pepper", "black pepper", "oil", "olive oil",
    "vegetable oil", "water", "sugar",
}

SUPPORTING_INGREDIENTS = {
    "allspice", "basil", "bay leaves", "black pepper", "cardamom",
    "cayenne pepper", "chili flakes", "chili powder", "cinnamon", "cloves",
    "coriander", "cumin", "curry powder", "dried parsley", "fennel seeds",
    "five spice powder", "garam masala", "garlic powder", "ginger",
    "italian seasoning", "mustard seeds", "nutmeg", "old bay seasoning",
    "onion powder", "oregano", "paprika", "red pepper flakes", "rosemary",
    "sage", "saffron", "salt", "smoked paprika", "sumac", "thyme",
    "turmeric", "vanilla extract", "za'atar",
}

INGREDIENT_ALIASES = {
    "chicken breast meat": "chicken breast",
    "chicken thighs": "chicken",
    "garlic cloves": "garlic",
}

QUERY_PRIORITY_TERMS = {
    "beef", "chicken", "chicken breast", "fish", "pasta", "pork", "rice",
    "salmon", "shrimp", "tofu", "turkey",
}

PASTA_TERMS = {
    "bucatini", "farfalle", "fettuccine", "linguine", "macaroni", "mostaccioli",
    "noodles", "orecchiette", "penne", "rigatoni", "shells", "spaghetti",
    "tagliatelle", "tortellini", "ziti",
}

MEAL_ANCHORS = {
    "beef", "chicken", "chicken breast", "fish", "pasta", "pork", "rice",
    "salmon", "shrimp", "tofu", "turkey",
}


class ApiKeyMissingError(RuntimeError):
    pass


def _require_spoonacular_key():
    if not SPOONACULAR_API_KEY:
        raise ApiKeyMissingError(
            "SPOONACULAR_API_KEY is not set. Add it to backend/.env (see .env.example)."
        )


def normalize_ingredient_name(name):
    """Lowercase and trim punctuation so Spoonacular and user terms compare cleanly."""
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", name.lower())).strip()
    return INGREDIENT_ALIASES.get(normalized, normalized)


def base_ingredient_name(ingredient):
    name = ingredient.get("name") or ingredient.get("originalName") or ingredient.get("original") or ""
    return normalize_ingredient_name(name)


def ingredient_terms_match(requested, candidate):
    requested = normalize_ingredient_name(requested)
    candidate = normalize_ingredient_name(candidate)
    if not requested or not candidate:
        return False
    if requested in candidate or candidate in requested:
        return True
    if requested == "pasta" and any(term in candidate for term in PASTA_TERMS):
        return True
    if candidate == "pasta" and any(term in requested for term in PASTA_TERMS):
        return True
    if requested.startswith("chicken ") and "chicken" in candidate:
        return True
    if candidate.startswith("chicken ") and "chicken" in requested:
        return True
    return False


def is_supporting_ingredient(name, spice_inventory=None, staples_whitelist=None):
    normalized = normalize_ingredient_name(name)
    supporting = set(SUPPORTING_INGREDIENTS)
    supporting.update(normalize_ingredient_name(s) for s in (spice_inventory or []))
    supporting.update(normalize_ingredient_name(s) for s in (staples_whitelist or DEFAULT_STAPLES_WHITELIST))
    return normalized in supporting


def core_ingredients(ingredients, spice_inventory=None, staples_whitelist=None):
    """Keep main ingredients for discovery; spices/staples should not drive recipe choice."""
    core = [
        ing for ing in ingredients
        if not is_supporting_ingredient(ing, spice_inventory, staples_whitelist)
    ]
    return core or list(ingredients)


def recipe_query_terms(ingredients, spice_inventory=None, staples_whitelist=None, limit=3):
    core = [normalize_ingredient_name(item) for item in core_ingredients(ingredients, spice_inventory, staples_whitelist)]
    priority = [item for item in core if item in QUERY_PRIORITY_TERMS or any(term in item for term in QUERY_PRIORITY_TERMS)]
    secondary = [item for item in core if item not in priority]
    seen = set()
    terms = []
    for item in priority + secondary:
        if item not in seen:
            terms.append(item)
            seen.add(item)
        if len(terms) >= limit:
            break
    return terms


def search_recipes_by_ingredients(ingredients, spice_inventory=None, number=50, ranking=1):
    """
    Step 1 (simple mode): get a ranked list of recipes by ingredient overlap.
    `ingredients` and `spice_inventory` are lists of strings (e.g. ["chicken breast", "broccoli"]).
    `ranking=1` maximizes used ingredients; `ranking=2` minimizes missing ingredients.
    """
    _require_spoonacular_key()
    combined = core_ingredients(ingredients, spice_inventory)
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "ingredients": ",".join(combined),
        "number": number,
        "ranking": ranking,
        "ignorePantry": True,
    }
    resp = requests.get(f"{SPOONACULAR_BASE}/recipes/findByIngredients", params=params)
    resp.raise_for_status()
    return resp.json()


def search_recipes_complex(ingredients, spice_inventory=None, diet=None, intolerances=None,
                            max_ready_time=None, number=50):
    """
    Step 1 (filtered mode): used when the user has set diet/intolerance/time filters,
    since complexSearch supports includeIngredients + diet + intolerances + maxReadyTime
    together in one call (spec 2.5).
    """
    _require_spoonacular_key()
    combined = core_ingredients(ingredients, spice_inventory)
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "includeIngredients": ",".join(combined),
        "query": " ".join(recipe_query_terms(ingredients, spice_inventory)),
        "number": number,
        "fillIngredients": True,
        "addRecipeInformation": False,
        "sort": "max-used-ingredients",
    }
    if diet:
        params["diet"] = ",".join(diet) if isinstance(diet, (list, tuple)) else diet
    if intolerances:
        params["intolerances"] = ",".join(intolerances) if isinstance(intolerances, (list, tuple)) else intolerances
    if max_ready_time:
        params["maxReadyTime"] = max_ready_time

    resp = requests.get(f"{SPOONACULAR_BASE}/recipes/complexSearch", params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


def search_recipes_by_query(ingredients, spice_inventory=None, diet=None, intolerances=None,
                            max_ready_time=None, number=50):
    """Search by the main-dish phrase, then let our scorer decide whether ingredients match."""
    _require_spoonacular_key()
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "query": " ".join(recipe_query_terms(ingredients, spice_inventory)),
        "number": number,
        "fillIngredients": True,
        "addRecipeInformation": False,
    }
    if diet:
        params["diet"] = ",".join(diet) if isinstance(diet, (list, tuple)) else diet
    if intolerances:
        params["intolerances"] = ",".join(intolerances) if isinstance(intolerances, (list, tuple)) else intolerances
    if max_ready_time:
        params["maxReadyTime"] = max_ready_time

    resp = requests.get(f"{SPOONACULAR_BASE}/recipes/complexSearch", params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


def autocomplete_ingredient(query, number=8):
    """Spoonacular GET /food/ingredients/autocomplete — for the ingredient text box (spec 2.1)."""
    _require_spoonacular_key()
    params = {"apiKey": SPOONACULAR_API_KEY, "query": query, "number": number}
    resp = requests.get(f"{SPOONACULAR_BASE}/food/ingredients/autocomplete", params=params)
    resp.raise_for_status()
    return resp.json()


def get_recipe_information(recipe_id, include_nutrition=False):
    """
    Step 2: get full instructions, ingredient list, default servings, and ready time.
    Uses fillIngredients=true so staples are included in the real ingredient list (spec 2.4).
    """
    _require_spoonacular_key()
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "includeNutrition": include_nutrition,
        "fillIngredients": True,
    }
    resp = requests.get(f"{SPOONACULAR_BASE}/recipes/{recipe_id}/information", params=params)
    resp.raise_for_status()
    return resp.json()


def scale_ingredients(extended_ingredients, desired_servings, default_servings):
    """
    Step 3: scale each ingredient's amount to the user's desired serving size.
    `extended_ingredients` is the `extendedIngredients` array from get_recipe_information().
    Returns a new list of dicts with a `scaledAmount` field added.
    """
    if not default_servings:
        default_servings = 1
    factor = desired_servings / default_servings

    scaled = []
    for ing in extended_ingredients:
        scaled.append({
            **ing,
            "scaledAmount": round(ing.get("amount", 0) * factor, 2),
        })
    return scaled


def filter_staples(missed_ingredients, staples_whitelist=None):
    """
    Step 4: remove staple items from a "missing ingredients" list before showing it to the user.
    `missed_ingredients` is the `missedIngredients` array from findByIngredients results.
    """
    whitelist = {s.lower() for s in (staples_whitelist or DEFAULT_STAPLES_WHITELIST)}
    return [
        ing for ing in missed_ingredients
        if ing.get("name", "").lower() not in whitelist
    ]


def score_recipe_match(recipe, user_ingredients, spice_inventory=None, staples_whitelist=None):
    """
    Score search results so main foods matter more than spices.

    Spoonacular's used/missed lists are useful, but they weight every term the
    same. This keeps spice matches from outranking recipes built around missing
    flour, pasta, etc.
    """
    supporting_names = {
        normalize_ingredient_name(item)
        for item in list(spice_inventory or []) + list(staples_whitelist or []) + list(SUPPORTING_INGREDIENTS)
    }
    requested_core = [
        normalize_ingredient_name(item)
        for item in core_ingredients(user_ingredients, spice_inventory, staples_whitelist)
    ]
    used = recipe.get("usedIngredients", [])
    missed = filter_staples(recipe.get("missedIngredients", []), staples_whitelist)

    used_core = [ing for ing in used if base_ingredient_name(ing) not in supporting_names]
    used_supporting = [ing for ing in used if base_ingredient_name(ing) in supporting_names]
    missed_core = [ing for ing in missed if base_ingredient_name(ing) not in supporting_names]

    used_core_names = {base_ingredient_name(ing) for ing in used_core}
    title = normalize_ingredient_name(recipe.get("title", ""))
    requested_core_hits = sum(
        1 for requested in requested_core
        if any(ingredient_terms_match(requested, used_name) for used_name in used_core_names)
    )
    title_hits = sum(1 for requested in requested_core if ingredient_terms_match(requested, title))
    anchor_terms = [
        requested for requested in requested_core
        if requested in MEAL_ANCHORS or any(anchor in requested for anchor in MEAL_ANCHORS)
    ]
    anchor_hits = sum(
        1 for requested in anchor_terms
        if ingredient_terms_match(requested, title)
        or any(ingredient_terms_match(requested, used_name) for used_name in used_core_names)
    )
    anchor_misses = max(0, len(anchor_terms) - anchor_hits)
    requested_hits = max(requested_core_hits, title_hits)
    requested_misses = max(0, len(requested_core) - requested_hits)

    score = (
        requested_hits * 140
        + anchor_hits * 220
        + len(used_core) * 25
        + len(used_supporting) * 3
        + title_hits * 35
        - anchor_misses * 180
        - requested_misses * 80
        - len(missed_core) * 40
    )
    core_total = len(used_core) + len(missed_core)
    core_match_percent = round(100 * len(used_core) / core_total) if core_total else 0

    return {
        "score": score,
        "usedCoreIngredientCount": len(used_core),
        "missedCoreIngredientCount": len(missed_core),
        "requestedCoreIngredientCount": len(requested_core),
        "requestedCoreHitCount": requested_hits,
        "requestedCoreMissCount": requested_misses,
        "anchorIngredientHitCount": anchor_hits,
        "anchorIngredientMissCount": anchor_misses,
        "coreMatchPercent": core_match_percent,
    }


def get_recipe_nutrition(recipe_id):
    """
    Step 5: fetch Spoonacular's per-serving nutrition for a recipe.

    The recipe-information endpoint returns nutrients as a list, so normalize
    the headline values used by the frontend while preserving the full list.
    """
    info = get_recipe_information(recipe_id, include_nutrition=True)
    nutrition = info.get("nutrition") or {}
    nutrients = nutrition.get("nutrients") or []
    if not nutrients:
        raise RuntimeError("Spoonacular returned no nutrition data for this recipe.")
    by_name = {item.get("name", "").lower(): item for item in nutrients}

    def nutrient(name):
        item = by_name.get(name.lower())
        if not item:
            return None
        return {"amount": item.get("amount"), "unit": item.get("unit", "")}

    return {
        "calories": nutrient("Calories"),
        "protein": nutrient("Protein"),
        "fat": nutrient("Fat"),
        "carbs": nutrient("Carbohydrates"),
        "nutrients": nutrients,
        "properties": nutrition.get("properties", []),
        "flavonoids": nutrition.get("flavonoids", []),
        "ingredients": nutrition.get("ingredients", []),
    }
