"""
Spec 2.5 — quantity parsing/scaling (pure functions), plus the ETL field
parsers for the "Recipes and Reviews" dataset (R vectors, ISO durations).
"""

import sys
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))
sys.path.insert(0, str(REPO / "etl"))

from quantities import (  # noqa: E402
    parse_quantity, format_quantity, scale_quantity, format_scaled_ingredient,
)
from common import parse_r_vector, parse_iso_duration_minutes  # noqa: E402


class TestParseQuantity:
    def test_whole_number(self):
        assert parse_quantity("2") == (Fraction(2), "")

    def test_simple_fraction(self):
        assert parse_quantity("3/4") == (Fraction(3, 4), "")

    def test_mixed_number(self):
        assert parse_quantity("1 1/2") == (Fraction(3, 2), "")

    def test_decimal(self):
        assert parse_quantity("2.5") == (Fraction(5, 2), "")

    def test_unicode_fraction_slash(self):
        assert parse_quantity("1⁄2") == (Fraction(1, 2), "")

    def test_unicode_vulgar_fraction(self):
        assert parse_quantity("1 ½") == (Fraction(3, 2), "")

    def test_trailing_text_kept(self):
        value, rest = parse_quantity("2 large")
        assert value == Fraction(2) and rest == "large"

    def test_range_not_scaled(self):
        value, rest = parse_quantity("2-3")
        assert value is None and rest == "2-3"

    def test_unparseable(self):
        assert parse_quantity("a pinch") == (None, "a pinch")
        assert parse_quantity(None) == (None, "")


class TestFormatQuantity:
    def test_whole(self):
        assert format_quantity(Fraction(2)) == "2"

    def test_fraction(self):
        assert format_quantity(Fraction(3, 4)) == "3/4"

    def test_mixed(self):
        assert format_quantity(Fraction(3, 2)) == "1 1/2"


class TestScaleQuantity:
    def test_double(self):
        assert scale_quantity("1 1/2", 2.0) == "3"

    def test_halve(self):
        assert scale_quantity("3", 0.5) == "1 1/2"

    def test_scale_with_trailing_text(self):
        assert scale_quantity("2 large", 1.5) == "3 large"

    def test_unparseable_passes_through(self):
        assert scale_quantity("a pinch", 2.0) == "a pinch"

    def test_none(self):
        assert scale_quantity(None, 2.0) is None

    def test_identity(self):
        assert scale_quantity("3/4", 1.0) == "3/4"


class TestFormatScaledIngredient:
    """Cook-friendly, name-aware quantity display (recipe-usability feedback:
    "1 1/3 chicken breasts" / "1 1/3 onions" aren't followable)."""

    def test_protein_converts_to_weight(self):
        # 1 chicken breast scaled 4/3 -> ~227g, kept with a rounded piece count.
        out = format_scaled_ingredient("chicken breasts", "1", Fraction(4, 3))
        assert out == "225 g (about 1 1/2)"

    def test_protein_large_amount_uses_pounds(self):
        out = format_scaled_ingredient("chicken breasts", "6", 1.0)
        assert out.endswith("lb (about 6)")

    def test_descriptor_stripped_before_matching(self):
        out = format_scaled_ingredient("boneless skinless chicken breasts", "1", Fraction(4, 3))
        assert "g (about" in out

    def test_whole_produce_rounds_to_half_not_thirds(self):
        # 1 onion scaled 4/3 -> 1 1/3 raw, rounds to the nearest half.
        assert format_scaled_ingredient("onions", "1", Fraction(4, 3)) == "1 1/2"

    def test_small_discrete_item_rounds_to_whole(self):
        assert format_scaled_ingredient("garlic", "4", Fraction(2, 3)) == "3"
        assert format_scaled_ingredient("eggs", "1", Fraction(1, 3)) == "1"  # never rounds to 0

    def test_unit_text_left_alone(self):
        # Already has a real unit -> trust it, don't reinterpret as a piece count.
        out = format_scaled_ingredient("chicken breast", "2 lb", 1.5)
        assert out == "3 lb"

    def test_spice_unaffected(self):
        assert format_scaled_ingredient("turmeric", "1/3", 2.0) == "2/3"

    def test_unparseable_passes_through(self):
        assert format_scaled_ingredient("salt", "a pinch", 2.0) == "a pinch"

    def test_bare_pasta_count_converts_to_grams_and_cups(self):
        # "2 pasta" isn't a real unit — dry pasta is measured by weight, and
        # in cups rather than a bare piece count.
        assert format_scaled_ingredient("pasta", "2", 1.0) == "170 g (about 1 1/2 cups)"
        assert format_scaled_ingredient("spaghetti", "1", 1.0) == "85 g (about 3/4 cup)"

    def test_bare_rice_count_converts_to_grams_and_cups(self):
        assert format_scaled_ingredient("rice", "1", 1.0) == "90 g (about 1/2 cup)"


class TestEtlParsers:
    def test_r_vector_string(self):
        assert parse_r_vector('c("flour", "sugar")') == ["flour", "sugar"]

    def test_r_vector_scalar(self):
        assert parse_r_vector('"salt"') == ["salt"]
        assert parse_r_vector("salt") == ["salt"]

    def test_r_vector_empty(self):
        assert parse_r_vector(None) == []
        assert parse_r_vector(float("nan")) == []
        assert parse_r_vector("NA") == []

    def test_r_vector_list_passthrough(self):
        assert parse_r_vector(["a", "b"]) == ["a", "b"]

    def test_iso_duration(self):
        assert parse_iso_duration_minutes("PT30M") == 30
        assert parse_iso_duration_minutes("PT1H30M") == 90
        assert parse_iso_duration_minutes("PT2H") == 120
        assert parse_iso_duration_minutes("P1DT1H") == 25 * 60

    def test_iso_duration_invalid(self):
        assert parse_iso_duration_minutes(None) is None
        assert parse_iso_duration_minutes("garbage") is None
