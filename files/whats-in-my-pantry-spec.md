# "What's In My Pantry" — Product & Technical Spec (v1)

> **Usage context:** this is a personal, non-commercial project for the builder's own use. Review Spoonacular's current plan limits and data-handling terms before expanding its use.

## 1. Product Summary

An app that takes the ingredients a user has on hand and returns recipes they can actually cook. This version uses a **hybrid API architecture**:
- **Spoonacular** for recipe discovery, ingredient matching, full step-by-step cooking instructions, and recipe nutrition.

V1 uses text-entry input; later versions add image/receipt scanning and a live inventory that depletes as recipes are cooked.

> **Why one provider works cleanly:** the Spoonacular recipe ID used for discovery also retrieves instructions and nutrition, so no cross-provider recipe matching or ingredient re-parsing is required.

---

## 2. V1 Feature Set

### 2.1 Input UI
- **Ingredient text box**: free-text, comma-or-newline separated, with autocomplete suggestions (Spoonacular's `GET /food/ingredients/autocomplete`).
- **Serving size**: numeric stepper (e.g. 1–12).
- **Time available**: dropdown or slider → maps to Spoonacular's `maxReadyTime`.
- **Dietary restrictions**: multi-select chips → Spoonacular's `diet` param (vegetarian, vegan, ketogenic, paleo, etc.) and `intolerances` param (dairy, egg, gluten, peanut, seafood, sesame, shellfish, soy, sulfite, tree nut, wheat) — keep these as two separate UI groups since they're two separate API concepts.
- **Spice/pantry tab** (see 2.3): a separate persistent section, not part of the per-search text box.

### 2.2 "Don't fail on staples" logic
1. Maintain a hardcoded **staples whitelist**: salt, pepper, oil, olive oil, water, sugar, etc.
2. Call `findByIngredients` with only the user's actual entered ingredients (don't inject staples into the query — it would skew ranking toward trivial matches).
3. Filter the response's `missedIngredients` against the staples whitelist before showing gaps to the user — show only real gaps.
4. Let users edit their own staples whitelist.

### 2.3 Spice inventory tab
- A dedicated tab where the user checks off spices they own from a curated list, stored persistently.
- At search time, merge `searchIngredients = mainTextBoxIngredients + userSpiceInventory` before calling Spoonacular.
- You'll maintain your own curated spice list client/server-side; Spoonacular doesn't expose a "spice" category flag on its own.

### 2.4 Always show basic spices in output
- Even though staples are excluded from *matching* logic, display the full real ingredient list and instructions to the user via `recipes/{id}/information` (with `fillIngredients=true`) — they still need to know to add salt when cooking.

### 2.5 Recipe results, instructions, and serving scaling
- Use `findByIngredients` for the initial ranked list (returns `usedIngredientCount`, `missedIngredientCount`, images cheaply).
- Use `complexSearch` with `includeIngredients` + `diet` + `intolerances` + `maxReadyTime` together when the user has set filters, since it supports all of those in one call.
- Call `recipes/{id}/information` for the recipe(s) the user opens, to get full instructions, ready time, and default servings.
- **Serving size scaling**: Spoonacular gives a default `servings` value; scale ingredient quantities client-side by `desiredServings / defaultServings`.

### 2.6 Nutrition via Spoonacular
This runs after a recipe is selected:

1. Request `recipes/{id}/information` with `includeNutrition=true`.
2. Read the per-serving values from `nutrition.nutrients`.
3. Display calories, protein, fat, and carbohydrates, while retaining the complete nutrient list for future UI expansion.
4. Cache results locally to reduce repeated API calls.

---

## 3. Suggested Additions for V1 (small lift, real value)

- **"Missing ingredients" shopping-list button**, built from Spoonacular's filtered `missedIngredients`.
- **Match percentage badge** on each recipe card ("You have 8/10 ingredients").
- **Sort/filter toggle**: fewest missing ingredients / fastest / best match.
- **Save/favorite recipes** — simple local list.
- **Empty/near-empty state handling** with a fallback suggestion (broaden filters, add a spice) rather than a blank screen.
- **Nutrition summary badges** (calories, protein) directly on the recipe card once the Spoonacular nutrition step has run, so users don't need to open full details to see the headline numbers.

---

## 4. Future Iterations

### 4.1 Additional input methods
- **Image of ingredients**: Spoonacular's single-food-photo classifier is not built for "identify everything in this fridge photo" — treat this as its own technical track, likely a general vision model.
- **Receipt scanning**: OCR → parse line items → fuzzy-match parsed strings against Spoonacular's ingredient search/autocomplete endpoint to normalize names.
- **Text entry**: already in V1.

### 4.2 Live inventory with auto-depletion
- Persistent **pantry table** (ingredient, quantity, unit, expiration date) in your own database.
- On recipe confirmation, pull the recipe's scaled ingredient list (2.5) and subtract from the pantry table.
- Unit conversion (recipe "2 tbsp" vs. pantry "500 ml") is the hard part — use a dedicated conversion utility rather than hand-rolling it.
- Prefer an editable "about to subtract this — adjust if needed" confirmation step over silent auto-depletion.
- Since nutrition (2.6) is now computed from the same scaled ingredient list used for depletion, you can reuse that exact ingredient array for both steps rather than building it twice.

---

## 5. Data Model Sketch

```
User
 - id, name, dietary_preferences[], intolerances[]

PantryItem (future: live inventory)
 - id, user_id, ingredient_name, quantity, unit, expiration_date

SpiceInventory
 - id, user_id, spice_name

SavedRecipe
 - id, user_id, spoonacular_recipe_id, saved_at

RecipeNutritionCache
 - id, spoonacular_recipe_id, serving_size, calories, macros_json, computed_at
   (cache key = recipe id + serving size, to avoid repeated Spoonacular calls)

StaplesWhitelist
 - id, user_id (nullable = global default), ingredient_name
```

---

## 6. Open Questions to Resolve Before Building
- Account system from day one, or local-storage-only for V1?
- Which Spoonacular plan tier and request limits fit the app's expected use?
- Do diet/intolerance filters apply per-search or as a saved, overridable user profile default? (Recommend: saved default, overridable per search.)
- Review Spoonacular's attribution and branding requirements before launch.
