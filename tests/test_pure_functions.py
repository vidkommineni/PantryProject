"""
V3 spec section 8 — unit tests for the pure functions: normalization (7.2),
scoring/re-ranking (7.3), the missing-count filter (7.4), and the token
matching rule behind exact-ID search (11.2). No database, no network.

Run from the repo root:  python -m pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

from normalize import (  # noqa: E402
    normalize_ingredient, normalize_ingredients, term_matches_vocab,
)
import search  # noqa: E402

STAPLES = ["salt", "pepper", "black pepper", "oil", "olive oil",
           "vegetable oil", "water", "sugar"]


# ---------------------------------------------------------------------------
# 7.2 normalization
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase_trim_whitespace(self):
        assert normalize_ingredient("  Chicken   Breast ") == "chicken breast"

    def test_strips_descriptor_tokens(self):
        assert normalize_ingredient("boneless skinless chicken breasts") == "chicken breasts"
        assert normalize_ingredient("fresh organic basil") == "basil"

    def test_synonym_mapping(self):
        assert normalize_ingredient("garbanzo beans") == "chickpeas"
        assert normalize_ingredient("aubergine") == "eggplant"
        assert normalize_ingredient("whey protein powder") == "protein powder"

    def test_all_descriptors_falls_back_to_original(self):
        assert normalize_ingredient("fresh organic") == "fresh organic"

    def test_empty_and_junk(self):
        assert normalize_ingredient("") == ""
        assert normalize_ingredient("   !!! ") == ""

    def test_list_dedup_order_preserving(self):
        out = normalize_ingredients(["Chicken", "fresh chicken", "rice", ""])
        assert out == ["chicken", "rice"]


# ---------------------------------------------------------------------------
# 11.2 exact matching rule — the spec's named regression cases
# ---------------------------------------------------------------------------

class TestTermMatching:
    def test_exact_match(self):
        assert term_matches_vocab("chicken", "chicken")

    def test_plural_insensitive(self):
        assert term_matches_vocab("onion", "onions")
        assert term_matches_vocab("tomatoes", "tomato")

    def test_cut_expansion_allowed(self):
        assert term_matches_vocab("chicken", "chicken breasts")
        assert term_matches_vocab("chicken", "chicken thighs")
        assert term_matches_vocab("garlic", "garlic cloves")

    def test_chicken_does_not_match_broth(self):
        # Spec 11.2: broth matches only if the user entered it or it's a staple.
        assert not term_matches_vocab("chicken", "chicken broth")
        assert not term_matches_vocab("chicken", "chicken stock")
        assert not term_matches_vocab("chicken", "cream of chicken soup")

    def test_chickpeas_never_match_chicken(self):
        # Spec 11.2: exact ID matching eliminates the substring confusion.
        assert not term_matches_vocab("chickpeas", "chicken")
        assert not term_matches_vocab("chicken", "chickpeas")

    def test_explicit_broth_entry_matches(self):
        assert term_matches_vocab("chicken broth", "chicken broth")

    def test_order_insensitive(self):
        assert term_matches_vocab("pepper bell", "bell pepper")


# ---------------------------------------------------------------------------
# 7.3 weighting / scoring
# ---------------------------------------------------------------------------

def _missing(*names):
    return [{"name": n} for n in names]


class TestWeightedMissing:
    def test_staple_weight_zero(self):
        assert search.weighted_missing(_missing("salt", "olive oil"), [], STAPLES) == 0.0

    def test_owned_spice_weight_quarter(self):
        assert search.weighted_missing(_missing("cumin"), ["cumin"], STAPLES) == 0.25

    def test_common_seasoning_weight_quarter(self):
        # In the spice-inventory *category* even if not owned (spec 7.3).
        assert search.weighted_missing(_missing("paprika"), [], STAPLES) == 0.25

    def test_core_weight_one(self):
        assert search.weighted_missing(_missing("chicken breasts"), [], STAPLES) == 1.0

    def test_mixed(self):
        got = search.weighted_missing(
            _missing("salt", "cumin", "chicken breasts"), ["cumin"], STAPLES)
        assert got == 1.25


class TestMatchRatio:
    def test_full_match(self):
        r = {"usedIngredients": [{"name": "rice"}], "missedIngredients": []}
        assert search.match_ratio(r, [], STAPLES) == 1.0

    def test_missing_only_staples_is_full_match(self):
        # Spec 7.3: missing only salt/oil ranks as effectively a full match.
        r = {"usedIngredients": [{"name": "rice"}],
             "missedIngredients": _missing("salt", "oil")}
        assert search.match_ratio(r, [], STAPLES) == 1.0

    def test_formula(self):
        r = {"usedIngredients": [{"name": "rice"}, {"name": "chicken"}],
             "missedIngredients": _missing("broccoli", "cumin")}
        # 2 / (2 + 1.0 + 0.25)
        assert abs(search.match_ratio(r, [], STAPLES) - 2 / 3.25) < 1e-9

    def test_zero_used(self):
        r = {"usedIngredients": [], "missedIngredients": _missing("beef")}
        assert search.match_ratio(r, [], STAPLES) == 0.0

    def test_spice_only_matches_weighted_down(self):
        # A match that came only from the spice inventory (core=False) earns
        # 0.25 credit, not 1.0 — seasonings must not drive recipe choice.
        r = {"usedIngredients": [{"name": "cumin", "core": False}],
             "missedIngredients": _missing("chicken breasts")}
        # 0.25 / (0.25 + 1.0)
        assert abs(search.match_ratio(r, [], STAPLES) - 0.2) < 1e-9

    def test_core_match_beats_spice_matches(self):
        # 1 typed ingredient beats 3 spice-inventory matches with equal gaps.
        core = {"usedIngredients": [{"name": "chicken breasts", "core": True}],
                "missedIngredients": _missing("broccoli")}
        spicy = {"usedIngredients": [{"name": "cumin", "core": False},
                                     {"name": "paprika", "core": False},
                                     {"name": "oregano", "core": False}],
                 "missedIngredients": _missing("broccoli")}
        assert search.match_ratio(core, [], STAPLES) > search.match_ratio(spicy, [], STAPLES)


class TestRealMissingCount:
    def test_excludes_staples_and_owned_spices(self):
        got = search.real_missing_count(
            _missing("salt", "cumin", "broccoli"), ["cumin"], STAPLES)
        assert got == 1

    def test_visible_missing_hides_staples_only(self):
        vis = search.visible_missing(_missing("salt", "cumin", "broccoli"), STAPLES)
        assert [i["name"] for i in vis] == ["cumin", "broccoli"]


# ---------------------------------------------------------------------------
# 7.3 re-ranking + 7.1 strategies + 7.4 filter
# ---------------------------------------------------------------------------

def _recipe(rid, used, missed, minutes=30, rating=None):
    return {
        "id": rid, "title": f"r{rid}", "minutes": minutes, "avgRating": rating,
        "nRatings": 10,
        "usedIngredients": [{"name": n} for n in used],
        "missedIngredients": [{"name": n} for n in missed],
    }


class TestRerank:
    def test_best_match_orders_by_ratio(self):
        full = _recipe(1, ["rice", "chicken"], ["salt"])
        partial = _recipe(2, ["rice"], ["beef", "broccoli"])
        ranked = search.rerank_results([partial, full], [], STAPLES)
        assert [r["id"] for r in ranked] == [1, 2]

    def test_rating_breaks_ties(self):
        a = _recipe(1, ["rice"], [], rating=4.2)
        b = _recipe(2, ["rice"], [], rating=4.9)
        ranked = search.rerank_results([a, b], [], STAPLES)
        assert ranked[0]["id"] == 2

    def test_fastest_strategy(self):
        slow = _recipe(1, ["rice"], [], minutes=90)
        fast = _recipe(2, ["rice"], ["beef"], minutes=10)
        ranked = search.rerank_results([slow, fast], [], STAPLES, strategy="fastest")
        assert ranked[0]["id"] == 2

    def test_input_not_mutated(self):
        original = _recipe(1, ["rice"], [])
        search.rerank_results([original], [], STAPLES)
        assert "matchRatio" not in original

    def test_annotations_added(self):
        ranked = search.rerank_results([_recipe(1, ["rice"], ["salt", "beef"])], [], STAPLES)
        assert ranked[0]["realMissingCount"] == 1
        assert ranked[0]["weightedMissing"] == 1.0
        assert ranked[0]["coreUsedCount"] == 1

    def test_user_ingredients_outrank_spice_matches(self):
        # Regression: recipes matching only the user's seasonings must not
        # outrank recipes matching the food they actually entered.
        spice_hit = {
            "id": 1, "title": "spice blend rub", "minutes": 5, "avgRating": 5.0,
            "nRatings": 500,
            "usedIngredients": [{"name": "cumin", "core": False},
                                {"name": "paprika", "core": False},
                                {"name": "chili powder", "core": False}],
            "missedIngredients": [],
        }
        food_hit = {
            "id": 2, "title": "chicken and rice", "minutes": 40, "avgRating": 4.0,
            "nRatings": 50,
            "usedIngredients": [{"name": "chicken breasts", "core": True},
                                {"name": "rice", "core": True}],
            "missedIngredients": [{"name": "onion"}],
        }
        ranked = search.rerank_results([spice_hit, food_hit], ["cumin", "paprika", "chili powder"], STAPLES)
        assert ranked[0]["id"] == 2


class TestFilterByMissingCount:
    def test_split(self):
        good = _recipe(1, ["rice"], ["beef"])
        bad = _recipe(2, ["rice"], ["beef", "pork", "lamb", "duck"])
        ranked = search.rerank_results([good, bad], [], STAPLES)
        primary, overflow = search.filter_by_missing_count(ranked, 2, [], STAPLES)
        assert [r["id"] for r in primary] == [1]
        assert [r["id"] for r in overflow] == [2]

    def test_zero_threshold_keeps_staple_only_missing(self):
        r = search.rerank_results([_recipe(1, ["rice"], ["salt"])], [], STAPLES)
        primary, overflow = search.filter_by_missing_count(r, 0, [], STAPLES)
        assert len(primary) == 1 and not overflow
