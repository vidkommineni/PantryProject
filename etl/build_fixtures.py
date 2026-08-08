"""
Spec section 8 — build the small checked-in fixture database
(data/fixtures.db): ~50 hand-picked recipes in exactly the same schema as the
full ETL output. Used by the unit tests, and by the app itself until the full
Food.com DB has been built. Idempotent.

    python etl/build_fixtures.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    DATA_DIR, create_schema, rebuild_fts, build_synonyms, build_diet_exclusions,
    diet_flags_from_tags, insert_recipe_ingredients, dumps, apply_quality_scores,
    build_name_exclusions,
)

# (id, name, minutes, tags, ingredients, steps, per-serving nutrition, rating, n_ratings)
# nutrition = (calories, fat g, sugar g, sodium mg, protein g, sat fat g, carbs g)
# Ingredient entries are either "name" or ("amount", "name") — both occur in
# the real dataset (some rows lack quantities), so fixtures exercise both.
FIXTURE_RECIPES = [
    (1, "classic chicken fried rice", 25, [],
     [("2", "chicken breasts"), ("3", "rice"), ("1", "onion"), ("2", "garlic"),
      ("3", "soy sauce"), ("2", "eggs"), ("2", "vegetable oil"), ("4", "green onions")],
     ["cook rice", "saute onion and garlic in oil", "add diced chicken and cook through",
      "push aside and scramble eggs", "stir in rice and soy sauce", "top with green onions"],
     (520, 18, 3, 890, 34, 4, 55), 4.6, 210),
    (2, "garlic butter chicken thighs", 35, [],
     [("6", "chicken thighs"), ("4", "butter"), ("4", "garlic"), ("2", "thyme"),
      ("1/2", "salt"), ("1/4", "black pepper")],
     ["season chicken", "sear skin side down", "add butter garlic thyme", "baste and roast"],
     (430, 30, 0, 520, 36, 12, 2), 4.8, 156),
    (3, "chickpea curry", 30, ["vegetarian", "vegan", "gluten-free"],
     [("2", "chickpeas"), ("1", "onion"), ("3", "garlic"), ("2", "tomatoes"),
      ("1", "coconut milk"), ("1 1/2", "curry powder"), ("1", "ginger"), ("2", "vegetable oil")],
     ["saute onion garlic ginger", "add curry powder", "add tomatoes and chickpeas",
      "simmer with coconut milk"],
     (380, 16, 8, 640, 12, 9, 48), 4.5, 320),
    (4, "vegetable stir fry", 20, ["vegetarian", "vegan"],
     [("2", "broccoli"), ("2", "carrots"), ("1", "bell pepper"), ("2", "garlic"),
      ("3", "soy sauce"), ("1", "sesame oil"), ("2", "rice")],
     ["cook rice", "stir fry vegetables", "add garlic and soy sauce", "finish with sesame oil"],
     (310, 8, 6, 720, 9, 1, 52), 4.2, 98),
    (5, "beef and broccoli", 30, [],
     [("1", "beef"), ("3", "broccoli"), ("2", "garlic"), ("1/4", "soy sauce"),
      ("1", "cornstarch"), ("2", "brown sugar"), ("1", "vegetable oil"), ("2", "rice")],
     ["slice beef and marinate", "stir fry beef", "add broccoli and sauce", "serve over rice"],
     (540, 22, 9, 980, 38, 6, 50), 4.7, 412),
    (6, "creamy tomato pasta", 25, ["vegetarian"],
     ["pasta", "tomatoes", "heavy cream", "garlic", "parmesan cheese", "basil", "olive oil"],
     ["boil pasta", "make tomato cream sauce", "toss with parmesan and basil"],
     (610, 24, 10, 560, 18, 12, 78), 4.4, 187),
    (7, "chicken noodle soup", 45, [],
     ["chicken broth", "egg noodles", "carrots", "celery", "onion", "chicken breasts", "thyme"],
     ["simmer chicken in broth", "add vegetables", "add noodles", "shred chicken and return"],
     (280, 8, 4, 940, 24, 2, 28), 4.6, 265),
    (8, "shrimp scampi", 20, [],
     ["shrimp", "garlic", "butter", "white wine", "lemon", "parsley", "pasta"],
     ["boil pasta", "saute garlic in butter", "add shrimp and wine", "toss with pasta"],
     (480, 18, 2, 720, 30, 9, 46), 4.5, 143),
    (9, "black bean tacos", 20, ["vegetarian", "vegan"],
     ["black beans", "corn tortillas", "onion", "cumin", "chili powder", "avocado", "lime", "cilantro"],
     ["warm beans with spices", "char tortillas", "assemble with avocado and cilantro"],
     (350, 12, 3, 610, 12, 2, 50), 4.3, 89),
    (10, "lamb rogan josh", 90, [],
     ["lamb", "onion", "garlic", "ginger", "yogurt", "garam masala", "tomatoes", "vegetable oil"],
     ["brown lamb", "cook onion spice base", "add tomatoes and yogurt", "simmer until tender"],
     (560, 34, 6, 680, 42, 12, 18), 4.7, 176),
    (11, "margherita pizza", 40, ["vegetarian"],
     ["pizza dough", "tomato sauce", "mozzarella cheese", "basil", "olive oil"],
     ["stretch dough", "top with sauce and cheese", "bake hot", "finish with basil"],
     (720, 26, 8, 1240, 28, 11, 92), 4.6, 331),
    (12, "salmon with roasted vegetables", 35, ["gluten-free"],
     ["salmon", "zucchini", "bell pepper", "red onion", "olive oil", "lemon", "dill"],
     ["roast vegetables", "add salmon fillets", "roast until flaky", "finish with lemon and dill"],
     (450, 24, 5, 380, 38, 4, 14), 4.5, 122),
    (13, "mushroom risotto", 50, ["vegetarian", "gluten-free"],
     ["arborio rice", "mushrooms", "onion", "garlic", "vegetable broth", "parmesan cheese", "butter", "white wine"],
     ["saute mushrooms", "toast rice", "add broth gradually", "finish with butter and parmesan"],
     (520, 18, 3, 840, 14, 9, 68), 4.4, 208),
    (14, "chicken caesar salad", 20, [],
     ["chicken breasts", "romaine lettuce", "parmesan cheese", "croutons", "caesar dressing", "lemon"],
     ["grill chicken", "toss lettuce with dressing", "top with chicken parmesan croutons"],
     (420, 24, 3, 880, 34, 6, 16), 4.2, 96),
    (15, "vegan lentil soup", 45, ["vegetarian", "vegan", "gluten-free"],
     ["lentils", "carrots", "celery", "onion", "garlic", "vegetable broth", "cumin", "tomatoes"],
     ["saute aromatics", "add lentils and broth", "simmer", "season and serve"],
     (290, 4, 6, 720, 16, 1, 48), 4.5, 274),
    (16, "pork chops with apples", 35, ["gluten-free"],
     ["pork chops", "apples", "onion", "butter", "thyme", "apple cider"],
     ["sear pork chops", "saute apples and onion", "deglaze with cider", "return chops to finish"],
     (480, 26, 14, 460, 36, 10, 22), 4.4, 118),
    (17, "eggplant parmesan", 60, ["vegetarian"],
     ["eggplant", "breadcrumbs", "eggs", "mozzarella cheese", "parmesan cheese", "tomato sauce", "basil", "olive oil"],
     ["bread and fry eggplant", "layer with sauce and cheese", "bake until bubbling"],
     (540, 28, 12, 1080, 22, 10, 52), 4.6, 199),
    (18, "thai green curry chicken", 40, ["gluten-free"],
     ["chicken breasts", "green curry paste", "coconut milk", "bamboo shoots", "bell pepper", "basil", "fish sauce", "rice"],
     ["fry curry paste", "add chicken", "add coconut milk and vegetables", "serve over rice"],
     (580, 28, 8, 920, 34, 18, 48), 4.7, 245),
    (19, "spaghetti carbonara", 25, [],
     ["spaghetti", "bacon", "eggs", "parmesan cheese", "black pepper"],
     ["boil spaghetti", "crisp bacon", "toss with egg and cheese off heat"],
     (620, 26, 2, 940, 28, 11, 66), 4.5, 388),
    (20, "tofu vegetable stir fry", 25, ["vegetarian", "vegan"],
     ["tofu", "broccoli", "carrots", "garlic", "ginger", "soy sauce", "sesame oil", "rice"],
     ["press and fry tofu", "stir fry vegetables", "combine with sauce", "serve over rice"],
     (380, 16, 6, 780, 20, 2, 42), 4.3, 134),
    (21, "banana oat pancakes", 20, ["vegetarian"],
     ["bananas", "oats", "eggs", "milk", "baking powder", "cinnamon", "maple syrup"],
     ["blend batter", "cook pancakes", "serve with maple syrup"],
     (340, 8, 18, 380, 12, 3, 58), 4.4, 167),
    (22, "greek salad", 15, ["vegetarian", "gluten-free"],
     ["cucumber", "tomatoes", "red onion", "feta cheese", "olives", "olive oil", "oregano", "lemon"],
     ["chop vegetables", "toss with oil lemon oregano", "top with feta and olives"],
     (260, 20, 6, 680, 8, 6, 14), 4.3, 92),
    (23, "beef chili", 75, ["gluten-free"],
     ["ground beef", "kidney beans", "onion", "garlic", "tomatoes", "chili powder", "cumin", "beef broth"],
     ["brown beef", "cook aromatics", "add beans tomatoes spices", "simmer low"],
     (460, 22, 8, 890, 32, 9, 34), 4.6, 356),
    (24, "chicken tikka masala", 60, ["gluten-free"],
     ["chicken breasts", "yogurt", "garam masala", "tomatoes", "heavy cream", "garlic", "ginger", "rice"],
     ["marinate chicken in yogurt and spices", "grill chicken", "simmer tomato cream sauce",
      "combine and serve over rice"],
     (620, 30, 9, 840, 40, 14, 46), 4.8, 502),
    (25, "quinoa stuffed peppers", 55, ["vegetarian", "gluten-free"],
     ["bell pepper", "quinoa", "black beans", "corn", "onion", "cumin", "cheddar cheese", "tomato sauce"],
     ["cook quinoa", "mix filling", "stuff peppers", "bake covered then uncovered"],
     (380, 12, 8, 640, 16, 5, 54), 4.2, 78),
    (26, "fish and chips", 50, [],
     ["cod", "flour", "beer", "potatoes", "vegetable oil", "salt"],
     ["cut and soak chips", "make beer batter", "fry chips", "fry battered fish"],
     (780, 38, 2, 820, 34, 6, 76), 4.4, 213),
    (27, "caprese sandwich", 10, ["vegetarian"],
     ["bread", "mozzarella cheese", "tomatoes", "basil", "balsamic vinegar", "olive oil"],
     ["slice bread and layer", "drizzle with balsamic and oil"],
     (420, 20, 6, 620, 18, 8, 44), 4.1, 45),
    (28, "shrimp fried rice", 25, [],
     ["shrimp", "rice", "eggs", "peas", "carrots", "soy sauce", "green onions", "vegetable oil"],
     ["scramble eggs", "stir fry shrimp", "add rice vegetables and sauce"],
     (490, 16, 4, 920, 28, 3, 58), 4.5, 189),
    (29, "butternut squash soup", 50, ["vegetarian", "gluten-free"],
     ["butternut squash", "onion", "garlic", "vegetable broth", "heavy cream", "nutmeg", "butter"],
     ["roast squash", "saute aromatics", "blend with broth", "finish with cream"],
     (320, 18, 10, 720, 6, 10, 36), 4.4, 156),
    (30, "turkey burgers", 30, [],
     ["ground turkey", "breadcrumbs", "eggs", "onion", "garlic powder", "burger buns", "lettuce", "tomatoes"],
     ["mix and form patties", "grill patties", "assemble burgers"],
     (440, 18, 5, 720, 34, 5, 38), 4.2, 103),
    (31, "vegan buddha bowl", 35, ["vegetarian", "vegan", "gluten-free"],
     ["quinoa", "sweet potatoes", "chickpeas", "kale", "avocado", "tahini", "lemon", "olive oil"],
     ["roast sweet potatoes and chickpeas", "cook quinoa", "massage kale",
      "assemble with tahini dressing"],
     (520, 24, 9, 480, 16, 3, 64), 4.6, 231),
    (32, "beef stroganoff", 45, [],
     ["beef", "mushrooms", "onion", "sour cream", "beef broth", "egg noodles", "butter", "flour"],
     ["sear beef", "cook mushrooms and onion", "make sauce", "toss with noodles"],
     (640, 32, 5, 860, 38, 15, 52), 4.5, 278),
    (33, "avocado toast with eggs", 10, ["vegetarian"],
     ["bread", "avocado", "eggs", "lemon", "red pepper flakes", "olive oil"],
     ["toast bread", "mash avocado with lemon", "top with fried eggs"],
     (380, 24, 2, 440, 14, 5, 30), 4.3, 87),
    (34, "minestrone soup", 50, ["vegetarian", "vegan"],
     ["cannellini beans", "pasta", "zucchini", "carrots", "celery", "onion", "tomatoes", "vegetable broth", "basil"],
     ["saute vegetables", "add broth tomatoes beans", "add pasta near the end"],
     (310, 6, 8, 780, 12, 1, 52), 4.4, 164),
    (35, "honey garlic salmon", 25, [],
     ["salmon", "honey", "garlic", "soy sauce", "lemon", "rice"],
     ["make honey garlic glaze", "sear salmon", "glaze and finish", "serve over rice"],
     (520, 20, 18, 880, 36, 4, 48), 4.7, 298),
    (36, "vegetarian chili", 60, ["vegetarian", "vegan", "gluten-free"],
     ["black beans", "kidney beans", "onion", "garlic", "bell pepper", "tomatoes",
      "chili powder", "cumin", "corn"],
     ["saute vegetables", "add beans tomatoes spices", "simmer"],
     (340, 6, 9, 760, 16, 1, 58), 4.3, 145),
    (37, "chicken parmesan", 50, [],
     ["chicken breasts", "breadcrumbs", "eggs", "flour", "mozzarella cheese",
      "parmesan cheese", "tomato sauce", "spaghetti"],
     ["bread chicken", "fry until golden", "top with sauce and cheese",
      "bake and serve over spaghetti"],
     (720, 30, 10, 1180, 48, 12, 62), 4.7, 445),
    (38, "pad thai", 35, [],
     ["rice noodles", "shrimp", "eggs", "bean sprouts", "peanuts", "fish sauce",
      "tamarind paste", "lime", "green onions"],
     ["soak noodles", "stir fry shrimp and eggs", "add noodles and sauce",
      "top with peanuts and lime"],
     (560, 20, 14, 1040, 28, 4, 68), 4.6, 267),
    (39, "ratatouille", 60, ["vegetarian", "vegan", "gluten-free"],
     ["eggplant", "zucchini", "bell pepper", "tomatoes", "onion", "garlic", "olive oil", "thyme"],
     ["slice vegetables", "layer in dish", "bake with oil and herbs"],
     (220, 12, 10, 380, 5, 2, 26), 4.3, 112),
    (40, "steak with chimichurri", 30, ["gluten-free"],
     ["steak", "parsley", "garlic", "red wine vinegar", "olive oil", "red pepper flakes"],
     ["make chimichurri", "sear steak to temp", "rest and slice", "serve with sauce"],
     (540, 38, 1, 420, 44, 12, 3), 4.7, 203),
    (41, "egg fried rice", 15, ["vegetarian"],
     ["rice", "eggs", "green onions", "soy sauce", "vegetable oil", "peas"],
     ["scramble eggs", "fry rice", "combine with sauce and peas"],
     (410, 14, 3, 820, 14, 3, 56), 4.2, 154),
    (42, "clam chowder", 55, [],
     ["clams", "potatoes", "onion", "celery", "heavy cream", "bacon", "butter", "flour"],
     ["render bacon", "cook vegetables", "make roux and add cream", "add clams"],
     (520, 30, 5, 940, 20, 16, 42), 4.4, 187),
    (43, "falafel wraps", 45, ["vegetarian", "vegan"],
     ["chickpeas", "onion", "garlic", "parsley", "cumin", "flour", "pita", "tahini", "cucumber"],
     ["blend falafel mix", "form and fry", "assemble wraps with tahini"],
     (480, 18, 5, 720, 16, 2, 64), 4.4, 176),
    (44, "roast chicken with potatoes", 90, ["gluten-free"],
     ["whole chicken", "potatoes", "lemon", "garlic", "rosemary", "olive oil", "butter"],
     ["season chicken", "roast over potatoes", "rest and carve"],
     (680, 38, 2, 640, 52, 12, 32), 4.8, 367),
    (45, "mac and cheese", 40, ["vegetarian"],
     ["macaroni", "cheddar cheese", "milk", "butter", "flour", "breadcrumbs", "mustard"],
     ["boil macaroni", "make cheese sauce", "combine and top with crumbs", "bake"],
     (660, 32, 8, 860, 24, 18, 68), 4.5, 312),
    (46, "tuna salad sandwich", 10, [],
     ["tuna", "mayonnaise", "celery", "red onion", "bread", "lettuce", "lemon"],
     ["mix tuna salad", "assemble sandwiches"],
     (380, 18, 4, 720, 26, 3, 32), 4.1, 67),
    (47, "sweet potato black bean bowl", 35, ["vegetarian", "vegan", "gluten-free"],
     ["sweet potatoes", "black beans", "rice", "avocado", "lime", "cumin", "cilantro", "olive oil"],
     ["roast sweet potatoes", "warm beans", "assemble bowls"],
     (460, 16, 10, 540, 14, 2, 68), 4.4, 132),
    (48, "beef tacos", 25, [],
     ["ground beef", "taco shells", "onion", "chili powder", "cumin", "cheddar cheese", "lettuce", "tomatoes"],
     ["brown beef with spices", "warm shells", "assemble tacos"],
     (480, 26, 4, 780, 28, 11, 34), 4.3, 221),
    (49, "vegetable omelette", 15, ["vegetarian", "gluten-free"],
     ["eggs", "bell pepper", "onion", "mushrooms", "cheddar cheese", "butter", "milk"],
     ["saute vegetables", "pour beaten eggs", "add cheese and fold"],
     (340, 24, 3, 520, 20, 11, 8), 4.2, 94),
    (50, "pesto pasta with chicken", 30, [],
     ["pasta", "chicken breasts", "basil pesto", "parmesan cheese", "olive oil", "pine nuts"],
     ["boil pasta", "cook chicken", "toss with pesto and parmesan"],
     (640, 30, 3, 720, 40, 8, 54), 4.5, 186),
    # Regression fixture (spec 11.2 follow-up): mirrors a real Food.com data
    # bug where a recipe's parsed ingredient list drops the very ingredient
    # its title promises ("shrimp" missing from RecipeIngredientParts). The
    # ingredient-based anti-join can't catch this; only the name-based one can.
    (51, "curried shrimp surprise", 25, [],
     ["onion", "curry powder", "sour cream"],
     ["cook onion with curry powder", "stir in sour cream"],
     (310, 8, 4, 480, 4, 12, 18), 4.0, 22),
]


def main(db_path=None):
    db_path = Path(db_path or DATA_DIR / "fixtures.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    create_schema(conn)

    for (rid, name, minutes, tags, ingredients, steps,
         nutri, rating, n_ratings) in FIXTURE_RECIPES:
        cal, fat, sugar, sodium, protein, satfat, carbs = nutri
        macros = {"fat": fat, "sugar": sugar, "sodium": sodium,
                  "protein": protein, "saturated_fat": satfat, "carbs": carbs}
        display = [
            {"amount": e[0], "name": e[1]} if isinstance(e, tuple)
            else {"amount": None, "name": e}
            for e in ingredients
        ]
        names = [d["name"] for d in display]
        conn.execute(
            """INSERT INTO recipes
               (id, name, minutes, n_steps, steps_json, description, n_ingredients,
                raw_ingredients_json, default_servings, avg_rating, n_ratings,
                calories, macros_json, diet_flags)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, name, minutes, len(steps), dumps(steps), "", len(names),
             dumps(display), 4, rating, n_ratings, float(cal), dumps(macros),
             diet_flags_from_tags(tags)))
        insert_recipe_ingredients(conn, rid, names)

    # n_ingredients must reflect the *indexed* count for the 11.1 arithmetic.
    conn.execute("""UPDATE recipes SET n_ingredients =
                    (SELECT COUNT(*) FROM recipe_ingredients
                     WHERE recipe_id = recipes.id)""")
    build_synonyms(conn)
    build_diet_exclusions(conn)
    build_name_exclusions(conn)
    rebuild_fts(conn)
    apply_quality_scores(conn)
    conn.commit()

    n = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    v = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
    conn.close()
    print(f"build_fixtures: {n} recipes, {v} vocabulary entries -> {db_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
