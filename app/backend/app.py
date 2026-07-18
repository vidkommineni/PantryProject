"""
Flask app for "What's In My Pantry" V1.

Serves the static frontend and exposes the JSON API it calls. Run with:
    python app.py
Then open http://localhost:5000 in a browser.

See README.md at the project root for setup (API keys, install steps).
"""

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import db
import pantry_api_client as api

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


# ---------- Ingredient autocomplete (spec 2.1) ----------

@app.route("/api/autocomplete", methods=["GET"])
def autocomplete():
    query = request.args.get("query", "")
    if not query:
        return jsonify({"suggestions": []})
    try:
        results = api.autocomplete_ingredient(query)
    except api.ApiKeyMissingError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(e)
    return jsonify({"suggestions": results})


# ---------- Search (spec 2.2, 2.3, 2.5, section 3) ----------

@app.route("/api/search", methods=["POST"])
def search():
    body = request.json or {}
    ingredients = body.get("ingredients", [])
    servings = int(body.get("servings", 4))
    max_ready_time = body.get("maxReadyTime")
    diet = body.get("diet", [])
    intolerances = body.get("intolerances", [])
    use_spices = body.get("useSpiceInventory", True)

    if not ingredients:
        return error_response("Provide at least one ingredient.", 400)

    spice_inventory = db.owned_spices() if use_spices else []
    staples = db.list_staples()

    try:
        if diet or intolerances or max_ready_time:
            raw_by_id = {}
            for r in api.search_recipes_by_ingredients(ingredients, spice_inventory):
                raw_by_id[r["id"]] = r
            for r in api.search_recipes_complex(
                ingredients, spice_inventory,
                diet=diet, intolerances=intolerances,
                max_ready_time=max_ready_time,
            ):
                raw_by_id.setdefault(r["id"], r)
            for r in api.search_recipes_by_query(
                ingredients, spice_inventory,
                diet=diet, intolerances=intolerances,
                max_ready_time=max_ready_time,
            ):
                raw_by_id.setdefault(r["id"], r)
            raw_results = list(raw_by_id.values())
            # complexSearch (fillIngredients) doesn't return used/missed counts the
            # same way findByIngredients does, so normalize a lighter-weight shape.
            results = []
            for r in raw_results:
                missed = r.get("missedIngredients", [])
                used = r.get("usedIngredients", [])
                recipe = {
                    "id": r["id"],
                    "title": r["title"],
                    "image": r.get("image"),
                    "usedIngredientCount": len(used),
                    "missedIngredientCount": len(filter_visible_missing(missed, staples)),
                    "missedIngredients": filter_visible_missing(missed, staples),
                    "usedIngredients": used,
                }
                recipe.update(api.score_recipe_match(recipe, ingredients, spice_inventory, staples))
                results.append(recipe)
        else:
            raw_results = api.search_recipes_by_ingredients(ingredients, spice_inventory)
            results = []
            for r in raw_results:
                missed = r.get("missedIngredients", [])
                recipe = {
                    "id": r["id"],
                    "title": r["title"],
                    "image": r.get("image"),
                    "usedIngredientCount": r.get("usedIngredientCount", 0),
                    "missedIngredientCount": len(filter_visible_missing(missed, staples)),
                    "missedIngredients": filter_visible_missing(missed, staples),
                    "usedIngredients": r.get("usedIngredients", []),
                }
                recipe.update(api.score_recipe_match(recipe, ingredients, spice_inventory, staples))
                results.append(recipe)
    except api.ApiKeyMissingError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(e)

    # Match percentage badge (spec section 3)
    for r in results:
        total = r["usedIngredientCount"] + r["missedIngredientCount"]
        r["matchPercent"] = round(100 * r["usedIngredientCount"] / total) if total else 0
        r["isFavorite"] = db.is_favorite(r["id"])
    results.sort(
        key=lambda r: (
            r.get("score", 0),
            -r.get("anchorIngredientMissCount", 0),
            -r.get("requestedCoreMissCount", 0),
            r.get("coreMatchPercent", 0),
            -r.get("missedCoreIngredientCount", 0),
            r.get("matchPercent", 0),
        ),
        reverse=True,
    )
    results = results[:10]

    if not results:
        return jsonify({
            "results": [],
            "emptyState": {
                "message": "No recipes matched. Try broadening your filters, "
                            "adding a spice you have on hand, or removing a dietary restriction.",
            },
        })

    return jsonify({"results": results})


def filter_visible_missing(missed_ingredients, staples):
    return api.filter_staples(missed_ingredients, staples)


# ---------- Recipe detail + scaling (spec 2.4, 2.5) ----------

@app.route("/api/recipe/<int:recipe_id>", methods=["GET"])
def recipe_detail(recipe_id):
    servings = int(request.args.get("servings", 4))
    try:
        info = api.get_recipe_information(recipe_id)
    except api.ApiKeyMissingError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(e)

    default_servings = info.get("servings", 1)
    scaled = api.scale_ingredients(info.get("extendedIngredients", []), servings, default_servings)

    return jsonify({
        "id": info.get("id"),
        "title": info.get("title"),
        "image": info.get("image"),
        "readyInMinutes": info.get("readyInMinutes"),
        "sourceUrl": info.get("sourceUrl"),
        "instructions": info.get("instructions"),
        "analyzedInstructions": info.get("analyzedInstructions", []),
        "defaultServings": default_servings,
        "requestedServings": servings,
        "scaledIngredients": scaled,
        "isFavorite": db.is_favorite(recipe_id),
    })


# ---------- Nutrition via Spoonacular ----------

@app.route("/api/recipe/<int:recipe_id>/nutrition", methods=["POST"])
def recipe_nutrition(recipe_id):
    body = request.json or {}
    servings = int(body.get("servings", 4))

    cached = db.get_cached_nutrition(recipe_id, servings)
    # Ignore entries created by the former nutrition provider. Spoonacular
    # entries use the normalized `nutrients` list and headline nutrient keys.
    if cached and "nutrients" in cached:
        cached["cached"] = True
        return jsonify(cached)

    try:
        nutrition = api.get_recipe_nutrition(recipe_id)
        nutrition["cached"] = False
    except api.ApiKeyMissingError as e:
        return error_response(e, 400)
    except Exception as e:
        return jsonify({
            "error": f"Nutrition lookup failed: {e}",
            "cached": False,
        }), 200

    db.cache_nutrition(recipe_id, servings, nutrition)
    return jsonify(nutrition)
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
