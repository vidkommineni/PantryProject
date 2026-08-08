"""
V4 spec section 15 — anchor-ingredient roles (pure functions, no I/O).

Problem this solves (spec 15 preamble): entering "chicken" used to return
pork recipes because every *other* ingredient matched and chicken was
outvoted in the 7.3 score. An anchor ingredient (a protein) expresses
intent — "I want a chicken recipe; I'm flexible on the rest" — so it is a
HARD constraint (15.2), not a scoring input:

  1. Must-contain: every anchor family the user entered must appear in the
     recipe ("chicken" is satisfied by "chicken breasts" via family match).
  2. No-conflict: the recipe must contain no anchor from a family the user
     didn't enter (chicken query -> pork recipes and surf-and-turf excluded;
     relax with allow_extra_anchors for a "strict protein match" UI toggle).
  3. No anchors entered -> everything passes; only scoring applies.

Derivative products (chicken broth, fish sauce, bacon fat) are never
anchors in either direction — they neither satisfy the chicken constraint
nor make a pork-broth recipe count as pork (spec 11.2 test case).

Builds on normalize.py: names are canonicalized with normalize_ingredient
(so "whey protein powder" -> "protein powder" before role lookup) and
compared at the singularized-token level via token_set.
"""

from normalize import normalize_ingredient, token_set

# Tokens that mark a derivative/flavor-base product. If any appears in an
# ingredient name, that ingredient is NOT an anchor regardless of what other
# tokens it contains ("chicken broth", "anchovy paste", "bacon fat", "beef
# bouillon cube", "oyster sauce").
DERIVATIVE_TOKENS = {
    "broth", "stock", "bouillon", "base", "gravy", "dripping", "drippings",
    "fat", "lard", "sauce", "paste", "seasoning", "flavoring", "flavor",
    "extract", "cube", "rind", "skin", "bit", "bits",
}

# Singularized anchor token -> protein family. Families let cuts unify
# ("chicken thigh" ~ "chicken breast") while different proteins conflict
# (chicken vs pork). Cut words (steak, chop, loin) are deliberately absent —
# they're ambiguous alone ("tuna steak") and normalize.CUT_WORDS already
# handles cut expansion at the vocabulary-matching layer.
#
# Eggs are deliberately NOT anchors: they appear in thousands of recipes as
# a binder, so anchor status would over-block (spec 15.1).
ANCHOR_TOKEN_FAMILIES = {
    # poultry
    "chicken": "chicken", "turkey": "turkey", "duck": "duck",
    # beef & co
    "beef": "beef", "sirloin": "beef", "ribeye": "beef", "brisket": "beef",
    "veal": "beef", "oxtail": "beef",
    # pork
    "pork": "pork", "bacon": "pork", "ham": "pork", "prosciutto": "pork",
    "pancetta": "pork", "sausage": "pork", "chorizo": "pork",
    "pepperoni": "pork", "salami": "pork", "spam": "pork",
    # lamb / game
    "lamb": "lamb", "mutton": "lamb", "venison": "venison", "rabbit": "rabbit",
    # fish
    "salmon": "fish", "tuna": "fish", "cod": "fish", "tilapia": "fish",
    "halibut": "fish", "trout": "fish", "snapper": "fish", "sardine": "fish",
    "anchovy": "fish", "anchovies": "fish", "catfish": "fish",
    "mackerel": "fish", "swordfish": "fish", "fish": "fish",
    # shellfish
    "shrimp": "shellfish", "prawn": "shellfish", "crab": "shellfish",
    "lobster": "shellfish", "scallop": "shellfish", "mussel": "shellfish",
    "clam": "shellfish", "oyster": "shellfish", "squid": "shellfish",
    "calamari": "shellfish", "octopus": "shellfish",
    # vegetarian anchors
    "tofu": "tofu", "tempeh": "tempeh", "seitan": "seitan", "paneer": "paneer",
    # supplement anchors — the original whey bug. normalize_ingredient folds
    # "whey protein powder" -> "protein powder"; the bare token covers
    # "chocolate protein powder", "protein shake mix", etc.
    "protein": "protein powder",
}


def families_of(name):
    """Anchor families present in one ingredient name -> set (usually 0-1).

    Derivative products return an empty set: "chicken broth" is not chicken.
    """
    canonical = normalize_ingredient(name)
    tokens = token_set(canonical)
    if tokens & DERIVATIVE_TOKENS:
        return set()
    return {ANCHOR_TOKEN_FAMILIES[t] for t in tokens if t in ANCHOR_TOKEN_FAMILIES}


def anchor_families(names):
    """Union of anchor families across a list of ingredient names."""
    fams = set()
    for name in names or []:
        fams |= families_of(name)
    return fams


def passes_anchor_filter(user_families, recipe_families, allow_extra_anchors=False):
    """Spec 15.2 hard filter. Pure set logic, deterministic.

    allow_extra_anchors=False (default, "strict protein match"): a chicken
    query rejects recipes that also contain shrimp. True permits recipes
    containing the user's anchor plus others.
    """
    if not user_families:
        return True
    if not user_families <= recipe_families:
        return False
    if not allow_extra_anchors and (recipe_families - user_families):
        return False
    return True


def candidate_anchor_families(candidate):
    """Anchor families for one search candidate dict (used + missed names)."""
    names = [
        ing.get("name", "")
        for ing in (candidate.get("usedIngredients") or [])
        + (candidate.get("missedIngredients") or [])
    ]
    return anchor_families(names)


def filter_candidates_by_anchor(candidates, user_families, allow_extra_anchors=False):
    """Apply the 15.2 hard filter to a candidate list — before scoring, like
    the 11.2 exclusions: a filtered recipe must never appear, regardless of
    match score. Returns a new list; input not mutated."""
    if not user_families:
        return list(candidates or [])
    return [
        c for c in (candidates or [])
        if passes_anchor_filter(
            user_families, candidate_anchor_families(c), allow_extra_anchors)
    ]
