"""
Nutrition plausibility guard (spec 11.4 follow-up): the dataset's per-recipe
nutrition is self-reported and sometimes simply wrong (e.g. a plain tomato
pasta sauce listing 1225 kcal / 45g protein per serving). build_payload should
surface a caveat rather than silently presenting numbers like that as fact.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

from nutrition import build_payload, plausibility_caveat  # noqa: E402


class TestPlausibilityCaveat:
    def test_flags_high_protein_with_no_protein_source(self):
        per_serving = {"calories": 1225.0, "protein": 45.0, "fat": 6.0, "carbs": 251.0}
        ingredients = ["tomatoes", "canned tomatoes", "onion", "garlic clove", "pasta"]
        caveat = plausibility_caveat(per_serving, ingredients)
        assert caveat is not None
        assert "protein" in caveat.lower()

    def test_no_caveat_when_protein_source_present(self):
        per_serving = {"calories": 550.0, "protein": 30.0, "fat": 20.0, "carbs": 50.0}
        ingredients = ["chicken breast", "rice", "broccoli"]
        assert plausibility_caveat(per_serving, ingredients) is None

    def test_flags_extreme_calories_regardless_of_ingredients(self):
        per_serving = {"calories": 5000.0, "protein": 10.0}
        assert plausibility_caveat(per_serving, ["rice", "water"]) is not None

    def test_no_caveat_for_ordinary_recipe(self):
        per_serving = {"calories": 420.0, "protein": 12.0, "fat": 15.0, "carbs": 60.0}
        assert plausibility_caveat(per_serving, ["flour", "sugar", "eggs", "milk"]) is None

    def test_missing_ingredient_list_does_not_crash(self):
        per_serving = {"calories": 300.0, "protein": 25.0}
        assert plausibility_caveat(per_serving, None) is not None  # no source -> flagged


class TestBuildPayloadCaveat:
    def test_payload_includes_caveat_key(self):
        per_serving = {"calories": 1225.0, "protein": 45.0, "fat": 6.0, "carbs": 251.0}
        payload = build_payload(per_serving, servings=2,
                                ingredient_names=["tomatoes", "onion", "pasta"])
        assert payload["caveat"] is not None

    def test_payload_caveat_none_for_clean_recipe(self):
        per_serving = {"calories": 420.0, "protein": 12.0, "fat": 15.0, "carbs": 60.0}
        payload = build_payload(per_serving, servings=4,
                                ingredient_names=["flour", "sugar", "eggs"])
        assert payload["caveat"] is None
