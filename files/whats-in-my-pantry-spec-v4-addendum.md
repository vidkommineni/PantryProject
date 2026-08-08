# Spec v4 Addendum — Section 15: Anchor-Ingredient Matching

> **Problem (observed):** entering "chicken" returns pork recipes because
> every *other* ingredient matched and chicken was outvoted in the score.
> Same class of bug as the earlier whey-protein mismatch. Root cause: the
> 7.3 score treats all user ingredients as equally optional. A protein entry
> is not optional — it expresses intent ("I want a chicken recipe; I'm
> flexible on the rest").
>
> **Why not embeddings or an LLM as the fix:** embedding similarity averages
> across ingredients — weighting chicken higher shifts the average but can
> never *guarantee* exclusion of pork. An LLM ranker is probabilistic for the
> same reason, plus latency/cost per search. The guarantee must be a
> deterministic rule. Embeddings and (optionally) a small LLM still have
> jobs — but at the *normalization* layer, not the ranking layer (15.4, 15.5).

## 15.1 Ingredient roles

Extend the vocabulary: every canonical ingredient gets one **role**:

| Role | Missing-weight (7.3) | Search behavior |
|---|---|---|
| `anchor` | n/a | **Hard constraint** (15.2) |
| `vegetable`, `grain`, `dairy`, `fruit`, `nut`, `legume`, `other` | 1.0 | normal scoring |
| `spice` | 0.25 | unchanged |
| `staple` | 0.0 | unchanged |

Anchors additionally carry an **anchor_family** (chicken, pork, beef, fish,
shellfish, tofu, protein powder, ...) so that "chicken thighs" and
"rotisserie chicken" unify, while chicken vs pork conflict.

**Derived non-anchors:** compounds like *chicken broth / stock / bouillon,
fish sauce, bacon bits* contain an anchor token but are flavor bases —
classified staple/spice, never anchor. This directly implements the 11.2
test case (broth neither satisfies nor triggers the chicken constraint).

**Eggs are deliberately not anchors** — they appear as binders everywhere;
anchor status would over-block. Documented in `roles.py`.

New ETL table (extends 10.4):

```
ingredient_roles (ingredient_id, role, anchor_family NULL)
```

Populated in `build_ingredient_index.py` by running `roles.classify()` /
`roles.anchor_family()` over the vocabulary.

## 15.2 Stage 1 — anchor hard filter (before scoring, like 11.2)

For the set `F` of anchor families in the user's entered ingredients:

1. **Must-contain:** recipe must contain ≥1 ingredient from *every* family
   in `F`.
2. **No-conflict:** recipe must contain **no** anchor ingredient from a
   family outside `F` (chicken query → surf-and-turf with shrimp excluded).
   Expose as a "strict protein match" toggle (`allow_extra_anchors`),
   default ON.
3. `F = ∅` (no anchor entered) → stage 1 passes everything; only
   `never_show` exclusions apply.

Applied as indexed SQL anti-joins in the 11.1 candidate query (see
`ANCHOR_FILTER_SQL` in `matcher.py`) — same pattern as the 11.2
diet-exclusion anti-join, so it is a hard filter that no score can leak past.

## 15.3 Stage 2 — ranking (unchanged)

7.3 scoring, 7.4 missing-cap, and tie-breakers apply only to recipes that
survived stage 1. Anchor coverage contributes no score — it's guaranteed.

## 15.4 Where embeddings fit: name normalization only

Use embeddings (or continue with `rapidfuzz`) to map free-text entries to
canonical vocabulary ingredients — "thighs" → chicken thigh, "whey protien"
→ whey protein. Recipe-level embedding similarity is explicitly rejected as
a ranking mechanism (see problem statement). Practical option: sentence
embeddings over the vocabulary (one-time, local, e.g. `model2vec` or
`sentence-transformers/all-MiniLM-L6-v2`) with nearest-neighbor lookup at
entry time; `rapidfuzz` is a fine v1 that handles the observed cases.

## 15.5 Where a small LLM fits (optional)

One job: classifying *new/unknown* ingredients into (canonical name, role,
anchor_family) when the lookup table misses — one cheap local call (e.g.
Ollama, keeping the no-API rule), result cached forever in
`ingredient_roles`. Never in the search path; never for filtering or
ranking. The chicken guarantee stays deterministic.

## 15.6 Layer summary (why nothing here is redundant)

| Layer | Job | Can the others do it? |
|---|---|---|
| Role table + hard filter | Correctness guarantee (chicken ⇒ chicken, ¬pork) | No — similarity can't guarantee exclusion |
| Embedding / fuzzy normalization | Typos, synonyms, phrasing | No — rules can't enumerate language |
| Small LLM (optional) | Classify unseen ingredients offline | Replaceable by hand-maintaining the table |

## 15.7 Regression tests (add to section 8 suite)

Implemented in `test_matcher.py` (13 tests, passing):
chicken never returns pork; chicken excludes anchor-free recipes;
chicken broth neither satisfies nor triggers the anchor; whey-protein query
returns only protein-powder recipes; no-anchor queries stay flexible;
strict-match toggle; `never_show` families; staples don't count as missing;
fewest-missing ranking.

## 15.8 Integration checklist

1. Copy `roles.py`, `matcher.py`, `test_matcher.py` into `app/` / `tests/`.
2. ETL: add `ingredient_roles` build step to `build_ingredient_index.py`
   (15.1); reuse `roles.normalize` in the 7.2 layer so both agree.
3. Search: add `ANCHOR_FILTER_SQL` clauses to the 11.1 query, or run
   `matcher.match()` in Python over the candidate set (fine at 30–200
   candidates).
4. UI: optional "strict protein match" toggle (default on) and surface the
   existing "never show me X" setting (11.2) which now also accepts
   anchor families.
