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
