"""
Flask app for "What's In My Pantry" — V3: fully local architecture.

No external API calls: recipes come from the local SQLite database built by
etl/run_all.py (Food.com dataset), with the checked-in data/fixtures.db as an
out-of-the-box fallback. Spoonacular is retired (spec Part III).

Run with:
    python app.py
Then open http://localhost:5000 in a browser.
"""

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import db
import nutrition
import recipe_store
import roles
import search as search_engine
from normalize import normalize_ingredients
from quantities import format_scaled_ingredient

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")

db.init_db()


def error_response(exc, status=500):
    return jsonify({"error": str(exc)}), status


# ---------- Static frontend ----------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------- Staples (spec 2.2) ----------

@app.route("/api/staples", methods=["GET"])
def get_staples():
    return jsonify({"staples": db.list_staples()})


@app.route("/api/staples", methods=["POST"])
def post_staple():
    name = (request.json or {}).get("name", "")
    db.add_staple(name)
    return jsonify({"staples": db.list_staples()})


@app.route("/api/staples/<name>", methods=["DELETE"])
def delete_staple(name):
    db.remove_staple(name)
    return jsonify({"staples": db.list_staples()})


# ---------- Spice inventory (spec 2.3) ----------

@app.route("/api/spices", methods=["GET"])
def get_spices():
    return jsonify({"spices": db.list_spices()})


@app.route("/api/spices/toggle", methods=["POST"])
def toggle_spice():
    body = request.json or {}
    name = body.get("name", "")
    owned = bool(body.get("owned", False))
    if not name:
        return error_response("Missing 'name'", 400)
    db.set_spice_owned(name, owned)
    return jsonify({"spices": db.list_spices()})


# ---------- "Never show me X" exclusions (spec 11.2) ----------

@app.route("/api/exclusions", methods=["GET"])
def get_exclusions():
    return jsonify({"exclusions": db.list_exclusions()})


@app.route("/api/exclusions", methods=["POST"])
def post_exclusion():
    name = (request.json or {}).get("name", "")
    if not name.strip():
        return error_response("Missing 'name'", 400)
    db.add_exclusion(name)
    return jsonify({"exclusions": db.list_exclusions()})


@app.route("/api/exclusions/<name>", methods=["DELETE"])
def delete_exclusion(name):
    db.remove_exclusion(name)
    return jsonify({"exclusions": db.list_exclusions()})


# ---------- Ingredient autocomplete (spec 11.3, local FTS5) ----------

@app.route("/api/autocomplete", methods=["GET"])
def autocomplete():
    query = request.args.get("query", "")
    if not query:
        return jsonify({"suggestions": []})
    try:
        return jsonify({"suggestions": recipe_store.autocomplete(query)})
    except recipe_store.RecipeDbMissingError as e:
        return error_response(e, 500)


# ---------- Search (spec 11.1 + 11.2 + 7.1/7.3/7.4) ----------

@app.route("/api/search", methods=["POST"])
def search():
    body = request.json or {}
    ingredients = body.get("ingredients", [])
    servings = int(body.get("servings", 4))
    max_ready_time = body.get("maxReadyTime")
    diets = body.get("diet", [])
    intolerances = body.get("intolerances", [])
    use_spices = body.get("useSpiceInventory", True)
    strict_protein = bool(body.get("strictProtein", True))
    strategy = body.get("sort") or search_engine.DEFAULT_RANKING
    try:
        max_missing = int(body.get("maxMissing", search_engine.DEFAULT_MAX_MISSING))
    except (TypeError, ValueError):
        max_missing = search_engine.DEFAULT_MAX_MISSING
    max_missing = max(0, min(4, max_missing))

    if not ingredients:
        return error_response("Provide at least one ingredient.", 400)

    spice_inventory = db.owned_spices() if use_spices else []
    staples = db.list_staples()

    try:
        # 7.2: normalize user terms; 2.3: merge owned spices into the query so a
        # recipe needing a spice the user has isn't counted as missing it.
        # Staples are NOT injected (2.2.2).
        # User-entered ingredients and spice-inventory terms are resolved
        # separately so scoring can prioritize the food the user actually
        # typed over incidental spice matches.
        user_terms = normalize_ingredients(ingredients)
        spice_terms = [t for t in normalize_ingredients(spice_inventory)
                       if t not in user_terms]
        user_term_ids = recipe_store.resolve_terms(user_terms)
        user_ids = set().union(*user_term_ids.values()) if user_term_ids else set()
        spice_term_ids = recipe_store.resolve_terms(spice_terms)
        spice_ids = (set().union(*spice_term_ids.values()) if spice_term_ids else set()) - user_ids
        matched_ids = user_ids | spice_ids

        # 11.2: user exclusions are hard filters applied before scoring.
        excluded_ids = set()
        for excl in db.list_exclusions():
            excluded_ids |= recipe_store.resolve_term_ids(excl)

        candidates = recipe_store.fetch_candidates(
            matched_ids,
            diets=diets,
            intolerances=intolerances,
            max_minutes=max_ready_time,
            excluded_ingredient_ids=excluded_ids,
            limit=search_engine.DEFAULT_CANDIDATE_COUNT,
        )
    except recipe_store.RecipeDbMissingError as e:
        return error_response(e, 500)

    # 15.2 — anchor hard filter, applied before scoring like the 11.2
    # exclusions: entering "chicken" means chicken recipes only; a recipe
    # anchored on a different protein (pork, shrimp, ...) must never appear,
    # regardless of how well its other ingredients match.
    user_anchor_fams = roles.anchor_families(ingredients)
    candidates = roles.filter_candidates_by_anchor(
        candidates, user_anchor_fams, allow_extra_anchors=not strict_protein)

    results = []
    for c in candidates:
        # Tag each match: core = matched a user-entered ingredient;
        # supporting = matched only via the spice inventory.
        for ing in c["usedIngredients"]:
            ing["core"] = ing.get("id") in user_ids
        core_used = search_engine.core_used_count(c["usedIngredients"])
        # A recipe that matches none of the user's actual ingredients is a
        # seasoning-only hit — never show it (unless the user typed only spices).
        if user_ids and core_used == 0:
            continue
        visible_missing = search_engine.visible_missing(c["missedIngredients"], staples)
        recipe = {
            "id": c["id"],
            "title": c["title"],
            "image": c.get("imageUrl"),
            "minutes": c.get("minutes"),
            "readyInMinutes": c.get("minutes"),
            "avgRating": c.get("avgRating"),
            "nRatings": c.get("nRatings"),
            "usedIngredientCount": len(c["usedIngredients"]),
            "missedIngredientCount": len(visible_missing),
            "usedIngredients": c["usedIngredients"],
            "missedIngredients": visible_missing,
        }
        total = recipe["usedIngredientCount"] + recipe["missedIngredientCount"]
        recipe["matchPercent"] = round(100 * recipe["usedIngredientCount"] / total) if total else 0
        recipe["isFavorite"] = db.is_favorite(recipe["id"])
        results.append(recipe)

    # 7.3 re-ranking with the 7.1 server-side strategy toggle.
    results = search_engine.rerank_results(
        results, spice_inventory, staples, strategy=strategy)

    # 7.4 — strong matches first; weaker ones collapse behind "show more".
    primary, overflow = search_engine.filter_by_missing_count(
        results, max_missing, spice_inventory, staples)
    primary = primary[:10]
    overflow = overflow[:10]

    if not primary and not overflow:
        if user_anchor_fams:
            fams = ", ".join(sorted(user_anchor_fams))
            message = (f"No recipes found featuring {fams} with your other "
                       "ingredients. Try adding a supporting ingredient "
                       "(an aromatic, a grain), raising the \"max missing\" "
                       "slider, or broadening your filters.")
        else:
            message = ("No recipes matched. Try broadening your filters, "
                       "adding a spice you have on hand, or removing a "
                       "dietary restriction.")
        return jsonify({
            "results": [], "overflowResults": [], "maxMissing": max_missing,
            "emptyState": {"message": message},
        })
    if not primary:
        return jsonify({
            "results": [], "overflowResults": overflow, "maxMissing": max_missing,
            "emptyState": {
                "message": f"No recipes with {max_missing} or fewer missing ingredients. "
                           "Showing the closest matches below — raise the "
                           "\"max missing\" slider to see more.",
            },
        })
    return jsonify({"results": primary, "overflowResults": overflow,
                    "maxMissing": max_missing, "servings": servings})


# ---------- Recipe detail (spec 2.4, 2.5) ----------

@app.route("/api/recipe/<int:recipe_id>", methods=["GET"])
def recipe_detail(recipe_id):
    servings = int(request.args.get("servings", 4))
    try:
        recipe = recipe_store.get_recipe(recipe_id)
    except recipe_store.RecipeDbMissingError as e:
        return error_response(e, 500)
    if recipe is None:
        return error_response("Recipe not found.", 404)

    # Spec 2.5 — scale ingredient quantities client-agnostically on the server:
    # factor = desiredServings / defaultServings.
    default_servings = recipe.get("default_servings") or 1
    factor = servings / default_servings
    scaled = []
    for ing in recipe.get("display_ingredients", []):
        scaled.append({
            "name": ing["name"],
            "amount": ing.get("amount"),
            "scaledAmount": format_scaled_ingredient(ing["name"], ing.get("amount"), factor),
        })

    return jsonify({
        "id": recipe["id"],
        "title": recipe["name"],
        "image": recipe.get("image_url"),
        "readyInMinutes": recipe.get("minutes"),
        "description": recipe.get("description") or "",
        "sourceUrl": f"https://www.food.com/recipe/{recipe['id']}",
        "steps": recipe.get("steps", []),
        "defaultServings": default_servings,
        "requestedServings": servings,
        "scaledIngredients": scaled,
        "avgRating": recipe.get("avg_rating"),
        "nRatings": recipe.get("n_ratings"),
        "isFavorite": db.is_favorite(recipe_id),
    })


# ---------- Nutrition — Tier 1, local (spec 11.4, implements 2.6) ----------

@app.route("/api/recipe/<int:recipe_id>/nutrition", methods=["POST"])
def recipe_nutrition(recipe_id):
    body = request.json or {}
    servings = int(body.get("servings", 4))
    try:
        per_serving = recipe_store.get_nutrition(recipe_id)
    except recipe_store.RecipeDbMissingError as e:
        return error_response(e, 500)
    if per_serving is None:
        return jsonify({"error": "No nutrition data for this recipe."}), 200
    # Tier-1 values are a single indexed read — no cache needed. The
    # RecipeNutritionCache table returns in Phase 4 for computed Tier-2 values.
    recipe = recipe_store.get_recipe(recipe_id)
    ingredient_names = recipe.get("ingredients") if recipe else None
    payload = nutrition.build_payload(per_serving, servings, ingredient_names)
    payload["cached"] = False
    return jsonify(payload)


# ---------- Favorites (spec section 3) ----------

@app.route("/api/favorites", methods=["GET"])
def get_favorites():
    return jsonify({"favorites": db.list_favorites()})


@app.route("/api/favorites", methods=["POST"])
def post_favorite():
    body = request.json or {}
    recipe_id = body.get("id")
    title = body.get("title", "")
    image = body.get("image", "")
    if not recipe_id:
        return error_response("Missing 'id'", 400)
    db.add_favorite(recipe_id, title, image)
    return jsonify({"favorites": db.list_favorites()})


@app.route("/api/favorites/<int:recipe_id>", methods=["DELETE"])
def delete_favorite(recipe_id):
    db.remove_favorite(recipe_id)
    return jsonify({"favorites": db.list_favorites()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
