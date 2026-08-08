"""
Spec 2.5 — serving-size scaling for ingredient quantities (pure functions).

Dataset quantities are strings like "2", "1/2", "1 1/2", "2 1⁄2" (unicode
fraction slash), occasionally with trailing text or ranges ("2-3"). Parse the
numeric part when possible, scale it by desiredServings / defaultServings, and
format the result back as a cook-friendly mixed fraction. Unparseable
quantities are passed through unscaled rather than dropped.
"""

from fractions import Fraction
import re

from normalize import normalize_ingredient, token_set

# Normalize unicode fraction characters before parsing.
UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
    "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}

_NUMBER = r"\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?"
# mixed number: "1 1/2" | simple: "3/4", "2", "2.5"
_QTY_RE = re.compile(rf"^\s*(\d+)\s+({_NUMBER})\s*(.*)$|^\s*({_NUMBER})\s*(.*)$")


def _clean(text):
    text = str(text)
    for uni, ascii_ in UNICODE_FRACTIONS.items():
        text = text.replace(uni, f" {ascii_}")
    return text.replace("⁄", "/").strip()


def _to_fraction(token):
    token = token.strip()
    if "/" in token:
        num, den = token.split("/", 1)
        den_val = float(den)
        if den_val == 0:
            return None
        return Fraction(float(num) / den_val).limit_denominator(16)
    return Fraction(float(token)).limit_denominator(16)


def parse_quantity(raw):
    """'1 1/2' -> (Fraction(3,2), ''); '2-3 large' -> (None, original).
    Returns (Fraction|None, trailing_text)."""
    if raw is None:
        return None, ""
    cleaned = _clean(raw)
    if not cleaned:
        return None, ""
    m = _QTY_RE.match(cleaned)
    if not m:
        return None, cleaned
    try:
        if m.group(1) is not None:  # mixed number
            value = Fraction(int(m.group(1))) + _to_fraction(m.group(2))
            rest = m.group(3) or ""
        else:
            value = _to_fraction(m.group(4))
            rest = m.group(5) or ""
    except (ValueError, ZeroDivisionError, TypeError):
        return None, cleaned
    if value is None:
        return None, cleaned
    if rest.startswith(("-", "–")):  # range like "2-3": don't pretend precision
        return None, cleaned
    return value, rest.strip()


def format_quantity(value):
    """Fraction -> cook-friendly string: 3/2 -> '1 1/2', 2 -> '2', 5/4 -> '1 1/4'."""
    value = value.limit_denominator(16)
    whole, rem = divmod(value.numerator, value.denominator)
    if rem == 0:
        return str(whole)
    frac = f"{rem}/{value.denominator}"
    return f"{whole} {frac}" if whole else frac


def scale_quantity(raw, factor):
    """Scale a quantity string by `factor`. Returns the scaled display string,
    or the original string when it can't be parsed (never None unless raw is)."""
    if raw is None:
        return None
    value, rest = parse_quantity(raw)
    if value is None:
        return str(raw).strip() or None
    scaled = value * Fraction(factor).limit_denominator(64)
    out = format_quantity(scaled)
    return f"{out} {rest}".strip() if rest else out


# ---------------------------------------------------------------------------
# Cook-friendly quantity formatting for whole/discrete ingredients.
#
# The dataset stores plain item counts with no unit ("1 1/3 chicken breasts",
# "1 1/3 onions"), and naive fraction scaling can land on thirds/eighths that
# nobody can actually measure out. This maps ingredient names to one of three
# treatments:
#   - proteins normally sold by weight -> convert to grams/lb, keep the
#     rounded piece count as a parenthetical for shopping
#   - discrete whole produce/aromatics -> round to the nearest half
#   - small discrete items (garlic cloves, eggs, ...) -> round to a whole count
# Everything else (spices measured in tsp/tbsp, liquids, items whose amount
# already carries a unit like "1 lb" or "2 cups") is left to scale_quantity.
# ---------------------------------------------------------------------------

# (required-token-set, grams per one unit, parenthetical style) — average
# kitchen weights. Ordered by specificity; the most specific matching group
# wins (e.g. "chicken breast" before bare "chicken").
#
# style "count": parenthetical repeats the rounded piece count, e.g.
#   "225 g (about 1 1/2)" for something naturally bought/counted by piece.
# style ("cups", grams_per_cup): parenthetical converts the total weight to a
#   cup measurement instead, e.g. "170 g (about 1 1/2 cups)" — dry pasta/rice
#   aren't bought or measured by "piece", so a volume makes more sense than a
#   bare count.
WEIGHT_PER_UNIT_G = [
    ({"chicken", "breast"}, 170, "count"),
    ({"chicken", "thigh"}, 120, "count"),
    ({"chicken", "drumstick"}, 90, "count"),
    ({"chicken", "wing"}, 45, "count"),
    ({"chicken", "tenderloin"}, 60, "count"),
    ({"chicken"}, 1300, "count"),          # whole chicken fallback
    ({"turkey", "breast"}, 900, "count"),
    ({"turkey", "cutlet"}, 120, "count"),
    ({"turkey"}, 5400, "count"),           # whole turkey fallback
    ({"pork", "chop"}, 200, "count"),
    ({"pork", "tenderloin"}, 450, "count"),
    ({"pork", "loin"}, 450, "count"),
    ({"lamb", "chop"}, 100, "count"),
    ({"beef", "steak"}, 250, "count"),
    ({"steak"}, 250, "count"),
    ({"salmon", "fillet"}, 170, "count"),
    ({"salmon"}, 170, "count"),
    ({"tilapia", "fillet"}, 140, "count"),
    ({"cod", "fillet"}, 150, "count"),
    ({"fish", "fillet"}, 150, "count"),
    ({"bacon"}, 20, "count"),              # per slice
    ({"sausage"}, 75, "count"),
    ({"ham", "slice"}, 30, "count"),
    # Dry pasta/grains are sold and cooked by weight, not by "1 pasta", and
    # measured in cups in the kitchen rather than by piece. ~85g is a
    # standard single dry-pasta serving; ~113g (~8oz/2cups) per cup.
    ({"spaghetti"}, 85, ("cups", 113)),
    ({"linguine"}, 85, ("cups", 113)),
    ({"fettuccine"}, 85, ("cups", 113)),
    ({"penne"}, 85, ("cups", 113)),
    ({"macaroni"}, 85, ("cups", 113)),
    ({"rigatoni"}, 85, ("cups", 113)),
    ({"noodle"}, 85, ("cups", 113)),
    ({"pasta"}, 85, ("cups", 113)),
    ({"rice"}, 90, ("cups", 185)),
]

# Whole produce/aromatics that read fine rounded to halves ("1 1/2 onions")
# but not to raw thirds/eighths.
ROUND_TO_HALF_TOKENS = [
    {"onion"}, {"tomato"}, {"potato"}, {"carrot"}, {"bell", "pepper"},
    {"pepper"}, {"lemon"}, {"lime"}, {"zucchini"}, {"apple"}, {"banana"},
    {"avocado"}, {"cucumber"}, {"mango"}, {"orange"}, {"eggplant"},
    {"peach"}, {"pear"}, {"plum"}, {"celery"},
]

# Small discrete items that only make sense as whole counts.
ROUND_TO_WHOLE_TOKENS = [
    {"garlic"}, {"egg"}, {"shallot"}, {"scallion"}, {"green", "onion"},
    {"jalapeno"}, {"chili"}, {"clove"},
]


def _best_weight_match(tokens):
    best = None
    for group, grams, style in WEIGHT_PER_UNIT_G:
        if group <= tokens and (best is None or len(group) > len(best[0])):
            best = (group, grams, style)
    return (best[1], best[2]) if best else None


def _format_cups(total_g, grams_per_cup):
    cups = Fraction(total_g / grams_per_cup).limit_denominator(4)
    if cups == 0 and total_g > 0:
        cups = Fraction(1, 4)
    unit = "cup" if cups <= 1 else "cups"
    return f"about {format_quantity(cups)} {unit}"


def _matches_any(tokens, groups):
    return any(group <= tokens for group in groups)


def _format_weight(grams):
    """225.4 -> '225 g'; 900+ -> pounds, e.g. '2 lb' / '1.5 lb'."""
    grams = max(5, round(grams / 5) * 5)
    if grams < 450:
        return f"{grams} g"
    lb = grams / 453.592
    lb_str = f"{lb:.1f}".rstrip("0").rstrip(".")
    return f"{lb_str} lb"


def format_scaled_ingredient(name, raw, factor):
    """
    Cook-friendly scaled amount for one display ingredient, taking its name
    into account (unlike scale_quantity, which is unit-blind).

    - proteins (chicken breast, pork chop, salmon fillet, ...): weight
      display with the rounded piece count alongside, e.g. "225 g (about 1 1/2)"
    - dry pasta/rice: weight display with a cup measurement alongside, e.g.
      "170 g (about 1 1/2 cups)"
    - discrete produce (onion, tomato, ...): rounded to the nearest half
    - small discrete items (garlic, egg, ...): rounded to a whole count
    - anything else, or an amount that already carries its own unit text
      ("2 cups", "1 lb", "14 oz can"): unchanged fraction scaling (spec 2.5)
    """
    value, rest = parse_quantity(raw)
    if value is None:
        return scale_quantity(raw, factor)

    scaled = value * Fraction(factor).limit_denominator(64)

    # Only recategorize bare item counts — if the dataset amount already
    # carries its own unit ("2 cups", "1 (14 oz) can"), trust that unit.
    if rest:
        out = format_quantity(scaled)
        return f"{out} {rest}".strip()

    tokens = token_set(normalize_ingredient(name))

    weight_match = _best_weight_match(tokens)
    if weight_match:
        grams_per_unit, style = weight_match
        total_g = float(scaled) * grams_per_unit
        if isinstance(style, tuple) and style[0] == "cups":
            paren = _format_cups(total_g, style[1])
        else:
            pieces = scaled.limit_denominator(2)
            if pieces == 0 and scaled > 0:
                pieces = Fraction(1, 2)
            paren = f"about {format_quantity(pieces)}"
        return f"{_format_weight(total_g)} ({paren})"

    if _matches_any(tokens, ROUND_TO_WHOLE_TOKENS):
        rounded = scaled.limit_denominator(1)
        if rounded == 0 and scaled > 0:
            rounded = Fraction(1)
        return format_quantity(rounded)

    if _matches_any(tokens, ROUND_TO_HALF_TOKENS):
        rounded = scaled.limit_denominator(2)
        if rounded == 0 and scaled > 0:
            rounded = Fraction(1, 2)
        return format_quantity(rounded)

    return format_quantity(scaled)
