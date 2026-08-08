"""
V3 spec section 8 — tests against the small checked-in fixture SQLite DB
(data/fixtures.db, built by etl/build_fixtures.py). No live APIs exist anymore;
this replaces the old fixture-JSON replay suite.

Includes the spec 11.2 regression cases:
  - "chickpeas + vegetarian" returns no meat recipes
  - "chicken" doesn't match recipes that merely contain chicken broth
  - "never show me X" exclusions are hard filters
"""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

FIXTURES_DB = REPO / "data" / "fixtures.db"
os.environ["PANTRY_DB"] = str(FIXTURES_DB)

import recipe_store  # noqa: E402
import search as search_engine  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_caches():
    recipe_store.clear_caches()
    yield


def _search(terms, **kwargs):
    term_ids = recipe_store.resolve_terms(terms)
    matched = set().union(*term_ids.values()) if term_ids else set()
    return recipe_store.fetch_candidates(matched, **kwargs)


def _titles(candidates):
    return {c["title"] for c in candidates}


MEAT_WORDS = {"chicken", "beef", "pork", "lamb", "bacon", "ham", "turkey",
              "shrimp", "fish", "salmon", "tuna", "clam", "cod", "steak"}


def _contains_meat(candidate):
    names = " ".join(
        i["name"] for i in candidate["usedIngredients"] + candidate["missedIngredients"])
    return any(w in names.split() or f"{w}s" in names.split() or w in names
               for w in MEAT_WORDS)


class TestPhase0Exit:
    def test_chicken_rice_onion_returns_recipes(self):
        # Spec Phase 0/1 exit criterion.
        results = _search(["chicken", "rice", "onion"])
        assert len(results) >= 5
        assert "classic chicken fried rice" in _titles(results)


class TestTermResolution:
    def test_chicken_resolves_to_cuts_not_broth(self):
        ids = recipe_store.resolve_term_ids("chicken")
        names = {name for i, name in recipe_store._vocab() if i in ids}
        assert "chicken breasts" in names
        assert "chicken thighs" in names
        assert "chicken broth" not in names
        assert "chickpeas" not in names

    def test_synonym_table(self):
        # "garbanzo beans" -> chickpeas via the synonym dictionary.
        ids = recipe_store.resolve_term_ids("garbanzo beans")
        names = {name for i, name in recipe_store._vocab() if i in ids}
        assert "chickpeas" in names


class TestDietEnforcement:
    def test_chickpeas_vegetarian_returns_no_meat(self):
        # Spec 11.2 named regression case.
        results = _search(["chickpeas"], diets=["vegetarian"])
        assert results, "expected vegetarian chickpea recipes"
        for c in results:
            assert not _contains_meat(c), f"meat leaked into: {c['title']}"

    def test_vegetarian_excludes_chicken_broth_recipes(self):
        # Belt-and-suspenders: broth is in the exclusion set even when the
        # recipe's tags are wrong/missing.
        results = _search(["onion", "carrots", "celery"], diets=["vegetarian"])
        assert "chicken noodle soup" not in _titles(results)

    def test_chicken_search_excludes_broth_only_recipes(self):
        # Spec 11.2: beef stroganoff contains beef broth-like items but no
        # chicken; a chicken search must not surface recipes that only have
        # a different protein or a broth.
        results = _search(["chicken"])
        titles = _titles(results)
        assert "beef stroganoff" not in titles
        assert "shrimp scampi" not in titles
        assert "lamb rogan josh" not in titles

    def test_vegan_excludes_dairy_and_egg(self):
        results = _search(["onion", "garlic", "tomatoes"], diets=["vegan"])
        assert results
        banned = {"butter", "cheese", "eggs", "milk", "yogurt", "heavy cream"}
        for c in results:
            names = {i["name"] for i in c["usedIngredients"] + c["missedIngredients"]}
            leaked = {n for n in names if any(b in n for b in banned)}
            assert not leaked, f"dairy/egg leaked into {c['title']}: {leaked}"

    def test_intolerance_shellfish(self):
        results = _search(["rice", "eggs"], intolerances=["shellfish"])
        assert "shrimp fried rice" not in _titles(results)
        assert "egg fried rice" in _titles(results)


class TestUserExclusions:
    def test_never_show_me_x_is_hard_filter(self):
        cilantro_ids = recipe_store.resolve_term_ids("cilantro")
        results = _search(["black beans"], excluded_ingredient_ids=cilantro_ids)
        titles = _titles(results)
        assert "black bean tacos" not in titles          # contains cilantro
        assert "vegetarian chili" in titles              # no cilantro

    def test_exclusion_applies_before_scoring(self):
        # Even a 100% match must never appear (spec 11.2).
        chicken_ids = recipe_store.resolve_term_ids("chicken")
        results = _search(["chicken breasts", "butter", "garlic", "thyme"],
                          excluded_ingredient_ids=chicken_ids)
        assert "garlic butter chicken thighs" not in _titles(results)


class TestFilters:
    def test_max_minutes(self):
        results = _search(["chicken"], max_minutes=30)
        for c in results:
            assert c["minutes"] <= 30

    def test_end_to_end_ranking(self):
        candidates = _search(["chicken", "rice", "onion", "garlic", "soy sauce", "eggs"])
        staples = ["salt", "pepper", "oil", "olive oil", "vegetable oil", "water", "sugar"]
        ranked = search_engine.rerank_results(candidates, [], staples)
        assert ranked[0]["title"] == "classic chicken fried rice"
        assert ranked[0]["matchRatio"] > 0.8


class TestDetailAndNutrition:
    def test_get_recipe(self):
        r = recipe_store.get_recipe(1)
        assert r["name"] == "classic chicken fried rice"
        assert len(r["steps"]) == 6
        assert "chicken breasts" in r["ingredients"]

    def test_display_ingredients_have_amounts(self):
        r = recipe_store.get_recipe(1)
        by_name = {d["name"]: d["amount"] for d in r["display_ingredients"]}
        assert by_name["chicken breasts"] == "2"
        assert by_name["rice"] == "3"

    def test_recipes_without_amounts_still_display(self):
        # Later fixtures are name-only, like real dataset rows missing quantities.
        r = recipe_store.get_recipe(50)
        assert all(d["amount"] is None for d in r["display_ingredients"])
        assert all(d["name"] for d in r["display_ingredients"])

    def test_get_recipe_missing(self):
        assert recipe_store.get_recipe(99999) is None

    def test_tier1_nutrition(self):
        n = recipe_store.get_nutrition(1)
        assert n["calories"] == 520
        assert n["protein"] == 34


class TestAutocomplete:
    def test_prefix(self):
        names = [s["name"] for s in recipe_store.autocomplete("chick")]
        assert any("chicken" in n for n in names)

    def test_empty(self):
        assert recipe_store.autocomplete("") == []
