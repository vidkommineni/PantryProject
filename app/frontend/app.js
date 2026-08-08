// "What's In My Pantry" — frontend logic (V1: text-entry, vanilla JS, talks to the Flask API).

const API = "/api";
let selectedDiet = new Set();
let selectedIntolerances = new Set();
let lastResults = [];
let lastOverflowResults = [];

// ---------- Max-missing slider (spec 7.4) ----------

const maxMissingInput = document.getElementById("max-missing");
const maxMissingValue = document.getElementById("max-missing-value");
maxMissingInput.addEventListener("input", () => {
  maxMissingValue.textContent = maxMissingInput.value;
});

// ---------- Tabs ----------

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "spices") loadSpices();
    if (btn.dataset.tab === "staples") loadStaples();
    if (btn.dataset.tab === "exclusions") loadExclusions();
    if (btn.dataset.tab === "favorites") loadFavorites();
  });
});

// ---------- Diet / intolerance chips ----------

function wireChipGroup(containerId, targetSet) {
  document.getElementById(containerId).addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const val = chip.dataset.value;
    if (targetSet.has(val)) {
      targetSet.delete(val);
      chip.classList.remove("selected");
    } else {
      targetSet.add(val);
      chip.classList.add("selected");
    }
  });
}
wireChipGroup("diet-chips", selectedDiet);
wireChipGroup("intolerance-chips", selectedIntolerances);

// ---------- Ingredient autocomplete ----------

const ingredientsBox = document.getElementById("ingredients-box");
const autocompleteList = document.getElementById("autocomplete-list");
let autocompleteTimer = null;

ingredientsBox.addEventListener("input", () => {
  clearTimeout(autocompleteTimer);
  const value = currentToken(ingredientsBox);
  if (!value || value.length < 2) {
    hideAutocomplete();
    return;
  }
  autocompleteTimer = setTimeout(() => fetchAutocomplete(value), 250);
});

function currentToken(textarea) {
  const text = textarea.value;
  const parts = text.split(/[,\n]/);
  return parts[parts.length - 1].trim();
}

async function fetchAutocomplete(query) {
  try {
    const res = await fetch(`${API}/autocomplete?query=${encodeURIComponent(query)}`);
    const data = await res.json();
    renderAutocomplete(data.suggestions || []);
  } catch (e) {
    hideAutocomplete();
  }
}

function renderAutocomplete(suggestions) {
  if (!suggestions.length) { hideAutocomplete(); return; }
  autocompleteList.innerHTML = "";
  suggestions.forEach(s => {
    const div = document.createElement("div");
    div.textContent = s.name;
    div.addEventListener("click", () => {
      const text = ingredientsBox.value;
      const parts = text.split(/([,\n])/);
      parts[parts.length - 1] = " " + s.name;
      ingredientsBox.value = parts.join("").replace(/^\s+/, "");
      hideAutocomplete();
      ingredientsBox.focus();
    });
    autocompleteList.appendChild(div);
  });
  autocompleteList.classList.add("show");
}

function hideAutocomplete() {
  autocompleteList.classList.remove("show");
  autocompleteList.innerHTML = "";
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".field")) hideAutocomplete();
});

// ---------- Search ----------

function parseIngredients(text) {
  return text
    .split(/[,\n]/)
    .map(s => s.trim())
    .filter(Boolean);
}

document.getElementById("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ingredients = parseIngredients(ingredientsBox.value);
  const statusEl = document.getElementById("search-status");
  const grid = document.getElementById("results-grid");
  const toolbar = document.getElementById("results-toolbar");

  if (!ingredients.length) {
    statusEl.textContent = "Enter at least one ingredient.";
    return;
  }

  statusEl.textContent = "Searching...";
  grid.innerHTML = "";
  toolbar.hidden = true;
  resetOverflowSection();

  const body = {
    ingredients,
    servings: parseInt(document.getElementById("servings").value, 10) || 4,
    maxReadyTime: document.getElementById("max-ready-time").value || null,
    diet: Array.from(selectedDiet),
    intolerances: Array.from(selectedIntolerances),
    useSpiceInventory: document.getElementById("use-spices").checked,
    strictProtein: document.getElementById("strict-protein").checked,
    maxMissing: parseInt(maxMissingInput.value, 10),
    sort: document.getElementById("sort-select").value,
  };

  try {
    const res = await fetch(`${API}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (data.error) {
      statusEl.innerHTML = `<div class="error-box">${escapeHtml(data.error)}</div>`;
      return;
    }

    lastResults = data.results || [];
    lastOverflowResults = data.overflowResults || [];

    if (!lastResults.length && !lastOverflowResults.length) {
      statusEl.textContent = data.emptyState?.message || "No recipes found.";
      return;
    }

    statusEl.textContent = data.emptyState?.message || "";
    toolbar.hidden = lastResults.length === 0;
    renderResults(lastResults, body.servings);
    renderOverflow(lastOverflowResults, body.servings, data.maxMissing);
  } catch (err) {
    statusEl.innerHTML = `<div class="error-box">Search failed: ${escapeHtml(String(err))}</div>`;
  }
});

// Re-running the search on sort change lets the server flip the ranking
// strategy (spec 7.1), not just reorder what we already have.
document.getElementById("sort-select").addEventListener("change", () => {
  document.getElementById("search-form").dispatchEvent(new Event("submit"));
});

// ---------- "Show more" overflow section (spec 7.4) ----------

function resetOverflowSection() {
  const section = document.getElementById("overflow-section");
  const overflowGrid = document.getElementById("overflow-grid");
  section.hidden = true;
  overflowGrid.hidden = true;
  overflowGrid.innerHTML = "";
}

function renderOverflow(results, servings, maxMissing) {
  const section = document.getElementById("overflow-section");
  const btn = document.getElementById("show-more-btn");
  const overflowGrid = document.getElementById("overflow-grid");

  if (!results.length) {
    section.hidden = true;
    return;
  }

  section.hidden = false;
  overflowGrid.hidden = true;
  overflowGrid.innerHTML = "";
  const threshold = maxMissing ?? parseInt(maxMissingInput.value, 10);
  btn.textContent = `Show ${results.length} more recipe${results.length === 1 ? "" : "s"} needing more than ${threshold} missing ingredient${threshold === 1 ? "" : "s"}`;

  btn.onclick = () => {
    if (overflowGrid.hidden) {
      overflowGrid.innerHTML = "";
      results.forEach(r => overflowGrid.appendChild(recipeCard(r, servings)));
      overflowGrid.hidden = false;
      btn.textContent = "Hide weaker matches";
    } else {
      overflowGrid.hidden = true;
      btn.textContent = `Show ${results.length} more recipe${results.length === 1 ? "" : "s"} needing more than ${threshold} missing ingredient${threshold === 1 ? "" : "s"}`;
    }
  };
}

function renderResults(results, servings, sortMode) {
  const grid = document.getElementById("results-grid");
  const mode = sortMode || document.getElementById("sort-select").value;
  // The server already re-ranked these (spec 7.3). "Fewest missing" re-sorts on
  // the real (staple/spice-aware) missing count; "best match" keeps server order.
  const sorted = mode === "missing"
    ? [...results].sort((a, b) => (
        (a.realMissingCount ?? a.missedIngredientCount) - (b.realMissingCount ?? b.missedIngredientCount) ||
        (b.matchRatio ?? 0) - (a.matchRatio ?? 0) ||
        (b.score ?? b.matchPercent) - (a.score ?? a.matchPercent)
      ))
    : [...results];
  grid.innerHTML = "";
  sorted.forEach(r => grid.appendChild(recipeCard(r, servings)));
}

function recipeCard(recipe, servings) {
  const card = document.createElement("div");
  card.className = "recipe-card";

  // V3: the local dataset has no images (spec 14) — text-first cards.
  card.appendChild(cardImage(recipe.image, recipe.title));

  const body = document.createElement("div");
  body.className = "recipe-card-body";

  const star = document.createElement("button");
  star.className = "fav-star" + (recipe.isFavorite ? " active" : "");
  star.textContent = recipe.isFavorite ? "★" : "☆";
  star.title = "Save recipe";
  star.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (star.classList.contains("active")) {
      await fetch(`${API}/favorites/${recipe.id}`, { method: "DELETE" });
      star.classList.remove("active");
      star.textContent = "☆";
    } else {
      await fetch(`${API}/favorites`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: recipe.id, title: recipe.title, image: recipe.image }),
      });
      star.classList.add("active");
      star.textContent = "★";
    }
  });
  body.appendChild(star);

  const h3 = document.createElement("h3");
  h3.textContent = recipe.title;
  body.appendChild(h3);

  const badgeRow = document.createElement("div");
  badgeRow.className = "badge-row";
  // realMissingCount (spec 7.3/7.4) excludes staples and spices you own, so the
  // badge reflects what you'd actually need to buy.
  const missing = recipe.realMissingCount ?? recipe.missedIngredientCount;
  const mins = recipe.readyInMinutes ?? recipe.minutes;
  badgeRow.innerHTML = `
    <span class="badge match">${recipe.matchPercent}% match (${recipe.usedIngredientCount}/${recipe.usedIngredientCount + recipe.missedIngredientCount})</span>
    ${missing > 0 ? `<span class="badge missing">${missing} missing</span>` : `<span class="badge match">All ingredients on hand</span>`}
    ${mins ? `<span class="badge">${mins} min</span>` : ""}
    ${recipe.avgRating ? `<span class="badge">★ ${Number(recipe.avgRating).toFixed(1)}${recipe.nRatings ? ` (${recipe.nRatings})` : ""}</span>` : ""}
  `;
  body.appendChild(badgeRow);

  card.appendChild(body);
  card.addEventListener("click", () => openRecipeModal(recipe.id, servings));
  return card;
}

// ---------- Recipe detail modal ----------

const modal = document.getElementById("recipe-modal");
const modalBody = document.getElementById("modal-body");

document.getElementById("modal-close").addEventListener("click", () => { modal.hidden = true; });
modal.addEventListener("click", (e) => { if (e.target === modal) modal.hidden = true; });

async function openRecipeModal(recipeId, servings) {
  modal.hidden = false;
  modalBody.innerHTML = "<p>Loading recipe...</p>";

  try {
    const res = await fetch(`${API}/recipe/${recipeId}?servings=${servings}`);
    const recipe = await res.json();
    if (recipe.error) {
      modalBody.innerHTML = `<div class="error-box">${escapeHtml(recipe.error)}</div>`;
      return;
    }
    renderRecipeDetail(recipe);
  } catch (err) {
    modalBody.innerHTML = `<div class="error-box">Failed to load recipe: ${escapeHtml(String(err))}</div>`;
  }
}

async function loadStaples() {
  const res = await fetch(`${API}/staples`);
  const data = await res.json();
  return data.staples || [];
}

async function renderRecipeDetail(recipe) {
  const staples = await loadStaples();
  const staplesSet = new Set(staples.map(s => s.toLowerCase()));

  // Spec 2.5: amounts are scaled server-side to the requested serving count.
  // Some dataset rows lack a quantity — show the name alone in that case.
  const ingredientItems = recipe.scaledIngredients.map(ing => {
    const isStaple = staplesSet.has((ing.name || "").toLowerCase());
    const amount = ing.scaledAmount ?? ing.amount ?? "";
    return `<li class="${isStaple ? "staple" : ""}">${escapeHtml(`${amount} ${ing.name || ""}`.trim())}${isStaple ? " (staple)" : ""}</li>`;
  }).join("");

  const missingForShoppingList = recipe.scaledIngredients.filter(
    ing => !staplesSet.has((ing.name || "").toLowerCase())
  );

  modalBody.innerHTML = `
    <h2>${escapeHtml(recipe.title)}</h2>
    <p>
      ${recipe.readyInMinutes ? `Ready in ${recipe.readyInMinutes} min &middot; ` : ""}
      ${recipe.avgRating ? `★ ${Number(recipe.avgRating).toFixed(1)}${recipe.nRatings ? ` (${recipe.nRatings} ratings)` : ""} &middot; ` : ""}
      Serves ${recipe.requestedServings}${recipe.defaultServings && recipe.defaultServings !== recipe.requestedServings ? ` (scaled from ${recipe.defaultServings})` : ""}
    </p>
    ${recipe.description ? `<p class="tab-desc">${escapeHtml(recipe.description)}</p>` : ""}
    <h3>Ingredients</h3>
    <ul class="ingredient-list">${ingredientItems}</ul>
    <button type="button" id="shopping-list-btn" class="secondary-btn shopping-list-btn">Copy missing-ingredients shopping list</button>
    <h3>Instructions</h3>
    ${renderInstructions(recipe)}
    <h3>Nutrition</h3>
    <div id="nutrition-area"><button type="button" id="load-nutrition-btn" class="secondary-btn">Show nutrition for this serving size</button></div>
    ${recipe.sourceUrl ? `<p><a href="${recipe.sourceUrl}" target="_blank" rel="noopener">View original source</a></p>` : ""}
  `;

  document.getElementById("shopping-list-btn").addEventListener("click", () => {
    const list = missingForShoppingList
      .map(ing => `${ing.scaledAmount ?? ing.amount ?? ""} ${ing.name || ""}`.trim())
      .join("\n");
    navigator.clipboard?.writeText(list).catch(() => {});
    alert("Shopping list copied to clipboard:\n\n" + list);
  });

  document.getElementById("load-nutrition-btn").addEventListener("click", () => loadNutrition(recipe));
}

function renderInstructions(recipe) {
  if (recipe.steps && recipe.steps.length) {
    return `<ol class="instructions-list">${recipe.steps.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ol>`;
  }
  return "<p>No instructions available.</p>";
}

async function loadNutrition(recipe) {
  const area = document.getElementById("nutrition-area");
  area.innerHTML = "<p>Calculating nutrition...</p>";
  try {
    const res = await fetch(`${API}/recipe/${recipe.id}/nutrition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        servings: recipe.requestedServings,
      }),
    });
    const data = await res.json();

    if (data.error) {
      area.innerHTML = `<div class="error-box">${escapeHtml(data.error)} — nutrition estimate incomplete.</div>`;
      return;
    }

    const formatNutrient = nutrient => nutrient?.amount == null
      ? null
      : `${Math.round(nutrient.amount)}${nutrient.unit || ""}`;
    const cal = formatNutrient(data.calories);
    const protein = formatNutrient(data.protein);
    const fat = formatNutrient(data.fat);
    const carbs = formatNutrient(data.carbs);

    const totalCal = data.totals?.calories
      ? `${Math.round(data.totals.calories.amount)}${data.totals.calories.unit || ""}`
      : null;
    area.innerHTML = `
      <p>Nutrition per serving</p>
      <div class="nutrition-box">
        ${cal !== null ? `<div><strong>${cal}</strong><br>calories</div>` : ""}
        ${protein !== null ? `<div><strong>${protein}</strong><br>protein</div>` : ""}
        ${fat !== null ? `<div><strong>${fat}</strong><br>fat</div>` : ""}
        ${carbs !== null ? `<div><strong>${carbs}</strong><br>carbs</div>` : ""}
      </div>
      ${totalCal && data.servings > 1 ? `<p style="font-size:0.8rem;color:var(--muted)">Total for ${data.servings} servings: ${totalCal} calories</p>` : ""}
      ${data.source ? `<p style="font-size:0.8rem;color:var(--muted)">${escapeHtml(data.source)}</p>` : ""}
      ${data.caveat ? `<p style="font-size:0.8rem;color:#b45309">⚠ ${escapeHtml(data.caveat)}</p>` : ""}
    `;
  } catch (err) {
    area.innerHTML = `<div class="error-box">Nutrition lookup failed: ${escapeHtml(String(err))}</div>`;
  }
}

// ---------- Spice inventory tab ----------

async function loadSpices() {
  const res = await fetch(`${API}/spices`);
  const data = await res.json();
  const grid = document.getElementById("spice-grid");
  grid.innerHTML = "";
  (data.spices || []).forEach(spice => {
    const chip = document.createElement("div");
    chip.className = "spice-chip" + (spice.owned ? " owned" : "");
    chip.innerHTML = `<input type="checkbox" ${spice.owned ? "checked" : ""}> ${spice.name}`;
    chip.addEventListener("click", async (e) => {
      const newOwned = !spice.owned;
      await fetch(`${API}/spices/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: spice.name, owned: newOwned }),
      });
      loadSpices();
    });
    grid.appendChild(chip);
  });
}

document.getElementById("add-spice-btn").addEventListener("click", async () => {
  const input = document.getElementById("new-spice-input");
  const name = input.value.trim();
  if (!name) return;
  await fetch(`${API}/spices/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, owned: true }),
  });
  input.value = "";
  loadSpices();
});

// ---------- Staples tab ----------

async function loadStaplesTab() {
  const staples = await loadStaples();
  const list = document.getElementById("staples-list");
  list.innerHTML = "";
  staples.forEach(name => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(name)}</span>`;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.title = "Remove staple";
    removeBtn.addEventListener("click", async () => {
      await fetch(`${API}/staples/${encodeURIComponent(name)}`, { method: "DELETE" });
      loadStaplesTab();
    });
    li.appendChild(removeBtn);
    list.appendChild(li);
  });
}

// override the loadStaples usage in the Staples tab wiring
document.querySelector('[data-tab="staples"]').addEventListener("click", loadStaplesTab);

document.getElementById("add-staple-btn").addEventListener("click", async () => {
  const input = document.getElementById("new-staple-input");
  const name = input.value.trim();
  if (!name) return;
  await fetch(`${API}/staples`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  input.value = "";
  loadStaplesTab();
});

// ---------- Favorites tab ----------

async function loadFavorites() {
  const res = await fetch(`${API}/favorites`);
  const data = await res.json();
  const grid = document.getElementById("favorites-grid");
  const empty = document.getElementById("favorites-empty");
  grid.innerHTML = "";
  const favorites = data.favorites || [];
  empty.hidden = favorites.length > 0;

  favorites.forEach(f => {
    const card = document.createElement("div");
    card.className = "recipe-card";
    card.appendChild(cardImage(f.image, f.title));
    const body = document.createElement("div");
    body.className = "recipe-card-body";
    body.innerHTML = `<h3>${escapeHtml(f.title)}</h3>`;
    card.appendChild(body);
    card.addEventListener("click", () => openRecipeModal(f.recipe_id, 4));
    grid.appendChild(card);
  });
}

// ---------- Exclusions tab (spec 11.2 "never show me X") ----------

async function loadExclusions() {
  const res = await fetch(`${API}/exclusions`);
  const data = await res.json();
  const list = document.getElementById("exclusions-list");
  list.innerHTML = "";
  (data.exclusions || []).forEach(name => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(name)}</span>`;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.title = "Remove exclusion";
    removeBtn.addEventListener("click", async () => {
      await fetch(`${API}/exclusions/${encodeURIComponent(name)}`, { method: "DELETE" });
      loadExclusions();
    });
    li.appendChild(removeBtn);
    list.appendChild(li);
  });
}

document.getElementById("add-exclusion-btn").addEventListener("click", async () => {
  const input = document.getElementById("new-exclusion-input");
  const name = input.value.trim();
  if (!name) return;
  await fetch(`${API}/exclusions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  input.value = "";
  loadExclusions();
});

// ---------- Utils ----------

function cardImage(imageUrl, title) {
  if (imageUrl) {
    const img = document.createElement("img");
    img.src = imageUrl;
    img.alt = title || "";
    return img;
  }
  const div = document.createElement("div");
  div.className = "card-image-placeholder";
  div.textContent = "🍲";
  return div;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
