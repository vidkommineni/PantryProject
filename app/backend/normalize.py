"""
V3 spec 7.2 — ingredient normalization layer (pure functions, no I/O).

Turns raw user-entered ingredient strings into canonical terms that match the
local Food.com-derived vocabulary, and provides the token-level matching rules
used to map a user term to vocabulary ingredient IDs.

Matching philosophy (spec 11.2): matching is *exact at the ingredient-ID
level*, with a small controlled expansion for cuts/forms ("chicken" may match
"chicken breasts") but never for derivative products ("chicken" must NOT match
"chicken broth", and "chickpeas" must never match "chicken").
"""

import re

# Descriptor / brand-ish tokens that add no matching value (spec 7.2 step 2).
DESCRIPTOR_TOKENS = {
    "baby", "boneless", "canned", "chilled", "chopped", "cold", "cooked",
    "diced", "dried", "extra", "fine", "finely", "fresh", "freshly", "frozen",
    "grated", "ground", "large", "lean", "low", "medium", "minced", "natural",
    "organic", "plain", "powdered", "premium", "raw", "ripe", "roasted",
    "shredded", "skinless", "sliced", "small", "thick", "thin", "unsalted",
    "unsweetened", "whole", "whey",
}

# Canonical-name mapping (spec 7.2 step 3). In v3 the canonical vocabulary is
# the dataset's own distinct ingredient names; this dictionary folds common
# variants into the names Food.com actually uses.
INGREDIENT_SYNONYMS = {
    "whey chocolate protein powder": "chocolate protein powder",
    "whey protein powder": "protein powder",
    "protein powder chocolate": "chocolate protein powder",
    "scallions": "green onions",
    "spring onions": "green onions",
    "coriander leaves": "cilantro",
    "aubergine": "eggplant",
    "courgette": "zucchini",
    "capsicum": "bell pepper",
    "garbanzo beans": "chickpeas",
    "passata": "tomato sauce",
    "curd": "yogurt",
    "maida": "flour",
    "all purpose flour": "flour",
    "confectioners sugar": "powdered sugar",
    "castor sugar": "sugar",
    "bicarbonate of soda": "baking soda",
    "double cream": "heavy cream",
    "single cream": "light cream",
    "minced beef": "ground beef",
    "mince": "ground beef",
    "prawns": "shrimp",
    "rocket": "arugula",
}

# Controlled expansion (spec 11.2): a user term may match a vocabulary entry
# that adds ONLY these cut/part words. Anything else ("broth", "stock",
# "soup", "bouillon", "flavor", ...) is a different product and must not match.
CUT_WORDS = {
    "breast", "breasts", "thigh", "thighs", "drumstick", "drumsticks",
    "leg", "legs", "wing", "wings", "fillet", "fillets", "filet", "filets",
    "tenderloin", "tenderloins", "cutlet", "cutlets", "chop", "chops",
    "steak", "steaks", "loin", "shoulder", "clove", "cloves", "bulb", "bulbs",
    "stalk", "stalks", "floret", "florets", "head", "heads", "leaf", "leaves",
}


def _singularize(token):
    """Light stemming so "onions" == "onion" and "berries" == "berry"."""
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("oes"):
        return token[:-2]  # tomatoes -> tomato, potatoes -> potato
    if len(token) > 3 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def clean_text(name):
    """Lowercase, strip punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())).strip()


def token_set(name):
    """Singularized token set for order-insensitive comparison."""
    return {_singularize(t) for t in clean_text(name).split(" ") if t}


def normalize_ingredient(name):
    """
    Spec 7.2 — one raw user/dataset ingredient -> canonical term.

    1. lowercase, strip punctuation, collapse whitespace
    2. synonym dictionary (full-phrase match first)
    3. strip descriptor tokens
    4. re-check the synonym dictionary on the stripped form
    Returns "" if nothing meaningful survives.
    """
    base = clean_text(name)
    if not base:
        return ""
    if base in INGREDIENT_SYNONYMS:
        return INGREDIENT_SYNONYMS[base]

    tokens = [t for t in base.split(" ") if t not in DESCRIPTOR_TOKENS]
    stripped = " ".join(tokens).strip() or base
    return INGREDIENT_SYNONYMS.get(stripped, stripped)


def normalize_ingredients(ingredients):
    """Normalize a list, de-duplicated, order-preserving. Originals are kept
    by callers for display; only these canonical values are matched."""
    normalized, seen = [], set()
    for item in ingredients or []:
        canonical = normalize_ingredient(item)
        if canonical and canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    return normalized


def term_matches_vocab(term, vocab_name):
    """
    Spec 11.2 exact-ID matching rule. True when the user's normalized `term`
    should map to vocabulary entry `vocab_name`:

      - identical token sets (singularized, order-insensitive), OR
      - vocab adds ONLY cut/part words ("chicken" -> "chicken breasts").

    Never true for derivative products ("chicken" vs "chicken broth") and never
    for substring confusion ("chickpeas" vs "chicken").
    """
    term_tokens = token_set(term)
    vocab_tokens = token_set(vocab_name)
    if not term_tokens or not vocab_tokens:
        return False
    if term_tokens == vocab_tokens:
        return True
    if term_tokens <= vocab_tokens:
        extra = vocab_tokens - term_tokens
        cut_singulars = {_singularize(c) for c in CUT_WORDS}
        return all(t in cut_singulars for t in extra)
    return False
