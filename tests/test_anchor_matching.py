"""
V4 spec section 15 — anchor-ingredient matching regression tests.

Covers the observed bugs: "chicken" returning pork recipes (anchor outvoted
by supporting-ingredient matches) and the earlier whey-protein mismatch.
No database, no network — pure functions over candidate dicts.

Run from the repo root:  python -m pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app" / "backend"))

import roles  # noqa: E402


def candidate(recipe_id, title, ingredient_names, used=0):
    """Build a search-candidate dict; first `used` ingredients are 'used'."""
    ings = [{"name": n, "id": i} for i, n in enumerate(ingredient_names)]
    return {
        "id": recipe_id, "title": title, "minutes": 30,
        "avgRating": 4.5, "nRatings": 10,
        "usedIngredients": ings[:used],
        "missedIngredients": ings[used:],
    }


FIXTURES = [
    candidate(1, "Garlic Chicken Rice",
              ["chicken thighs", "rice", "onion", "garlic", "olive oil", "salt"], used=4),
    candidate(2, "Pork Fried Rice",
              ["pork loin", "rice", "onion", "garlic", "soy sauce", "oil"], used=3),
    candidate(3, "Veggie Fried Rice",
              ["rice", "onion", "garlic", "carrots", "peas", "soy sauce"], used=3),
    candidate(4, "Pork Ramen",
              ["pork belly", "noodles", "chicken broth", "green onions", "eggs"], used=1),
    candidate(5, "Chicken Noodle Soup",
              ["chicken breasts", "noodles", "chicken broth", "carrots", "celery"], used=3),
    candidate(6, "Whey Protein Pancakes",
              ["protein powder", "oats", "bananas", "eggs", "baking powder"], used=3),
    candidate(7, "Banana Oat Pancakes",
              ["oats", "bananas", "eggs", "milk", "baking powder"], used=2),
    candidate(8, "Surf and Turf",
              ["chicken breasts", "shrimp", "butter", "garlic", "lemon"], used=2),
]


def titles(candidates):
    return [c["title"] for c in candidates]


# ---------------------------------------------------------------------------
# 15.1 — role/family classification
# ---------------------------------------------------------------------------

class TestFamilies:
    def test_cuts_unify_to_one_family(self):
        assert roles.families_of("boneless skinless chicken thighs") == {"chicken"}
        assert roles.families_of("chicken breasts") == {"chicken"}

    def test_different_proteins_are_different_families(self):
        assert roles.families_of("pork loin") == {"pork"}
        assert roles.families_of("ground beef") == {"beef"}
        assert roles.families_of("shrimp") == {"shellfish"}

    def test_whey_protein_normalizes_to_protein_powder_family(self):
        # normalize.py synonym mapping feeds the role lookup
        assert roles.families_of("whey protein powder") == {"protein powder"}
        assert roles.families_of("chocolate protein powder") == {"protein powder"}

    def test_derivatives_are_never_anchors(self):
        # spec 11.2 test case: broth neither satisfies nor triggers an anchor
        assert roles.families_of("chicken broth") == set()
        assert roles.families_of("chicken stock") == set()
        assert roles.families_of("fish sauce") == set()
        assert roles.families_of("anchovy paste") == set()
        assert roles.families_of("bacon bits") == set()

    def test_non_proteins_have_no_family(self):
        assert roles.families_of("rice") == set()
        assert roles.families_of("chickpeas") == set()  # never confused with chicken
        assert roles.families_of("eggs") == set()       # binder, deliberately not an anchor


# ---------------------------------------------------------------------------
# 15.2 — the hard filter (the chicken -> pork bug)
# ---------------------------------------------------------------------------

class TestAnchorFilter:
    def test_chicken_never_returns_pork(self):
        result = roles.filter_candidates_by_anchor(FIXTURES, {"chicken"})
        assert "Pork Fried Rice" not in titles(result)
        assert "Pork Ramen" not in titles(result)
        assert "Garlic Chicken Rice" in titles(result)

    def test_chicken_excludes_recipes_without_chicken(self):
        # even a perfect supporting match (veggie fried rice) is out —
        # the user asked for chicken
        result = roles.filter_candidates_by_anchor(FIXTURES, {"chicken"})
        assert "Veggie Fried Rice" not in titles(result)

    def test_broth_does_not_satisfy_the_chicken_anchor(self):
        # Pork Ramen contains "chicken broth" but is pork-anchored: excluded
        fams = roles.candidate_anchor_families(FIXTURES[3])
        assert fams == {"pork"}
        assert not roles.passes_anchor_filter({"chicken"}, fams)

    def test_whey_protein_bug(self):
        result = roles.filter_candidates_by_anchor(FIXTURES, {"protein powder"})
        assert titles(result) == ["Whey Protein Pancakes"]

    def test_no_anchor_entered_stays_flexible(self):
        result = roles.filter_candidates_by_anchor(FIXTURES, set())
        assert len(result) == len(FIXTURES)

    def test_strict_mode_excludes_extra_proteins(self):
        # Surf and Turf has chicken AND shrimp: strict chicken query drops it
        strict = roles.filter_candidates_by_anchor(FIXTURES, {"chicken"})
        assert "Surf and Turf" not in titles(strict)
        relaxed = roles.filter_candidates_by_anchor(
            FIXTURES, {"chicken"}, allow_extra_anchors=True)
        assert "Surf and Turf" in titles(relaxed)

    def test_multi_anchor_query_requires_all(self):
        result = roles.filter_candidates_by_anchor(FIXTURES, {"chicken", "shellfish"})
        assert titles(result) == ["Surf and Turf"]

    def test_user_entry_families_come_from_raw_strings(self):
        # what app.py does: families straight from what the user typed
        assert roles.anchor_families(["chicken", "rice", "onion"]) == {"chicken"}
        assert roles.anchor_families(["whey protein", "banana"]) == {"protein powder"}
        assert roles.anchor_families(["rice", "onion"]) == set()
