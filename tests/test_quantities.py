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

from quantities import parse_quantity, format_quantity, scale_quantity  # noqa: E402
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
