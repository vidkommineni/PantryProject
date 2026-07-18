// "What's In My Pantry" — frontend logic (V1: text-entry, vanilla JS, talks to the Flask API).

const API = "/api";
let selectedDiet = new Set();
let selectedIntolerances = new Set();
let lastResults = [];

// ---------- Tabs ----------

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "spices") loadSpices();
    if (btn.dataset.tab === "staples") loadStaples();
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

  const body = {
    ingredients,
    servings: parseInt(document.getElementById("servings").value, 10) || 4,
    maxReadyTime: document.getElementById("max-ready-time").value || null,
    diet: Array.from(selectedDiet),
    intolerances: Array.from(selectedIntolerances),
    useSpiceInventory: document.getElementById("use-spices").checked,
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

    if (!lastResults.length) {
      statusEl.textContent = data.emptyState?.message || "No recipes found.";
      return;
    }

    statusEl.textContent = "";
    toolbar.hidden = false;
    renderResults(lastResults, body.servings);
  } catch (err) {
    statusEl.innerHTML = `<div class="error-box">Search failed: ${escapeHtml(String(err))}</div>`;
  }
});

document.getElementById("sort-select").addEventListener("change", (e) => {
  const servings = parseInt(document.getElementById("servings").value, 10) || 4;
  renderResults(lastResults, servings, e.target.value);
});

function renderResults(results, servings, sortMode) {
  const grid = document.getElementById("results-grid");
  const mode = sortMode || document.getElementById("sort-select").value;
  const sorted = [...results].sort((a, b) => {
    if (mode === "missing") {
      return (
        (a.anchorIngredientMissCount ?? a.missedIngredientCount) - (b.anchorIngredientMissCount ?? b.missedIngredientCount) ||
        (a.requestedCoreMissCount ?? a.missedIngredientCount) - (b.requestedCoreMissCount ?? b.missedIngredientCount) ||
        (a.missedCoreIngredientCount ?? a.missedIngredientCount) - (b.missedCoreIngredientCount ?? b.missedIngredientCount) ||
        (b.score ?? b.matchPercent) - (a.score ?? a.matchPercent)
      );
    }
    return (b.score ?? b.matchPercent) - (a.score ?? a.matchPercent);
  });
  grid.innerHTML = "";
  sorted.forEach(r => grid.appendChild(recipeCard(r, servings)));
}

function recipeCard(recipe, servings) {
  const card = document.createElement("div");
  card.className = "recipe-card";

  const img = document.createElement("img");
  img.src = recipe.image || "";
  img.alt = recipe.title;
  card.appendChild(img);

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
  badgeRow.innerHTML = `
    <span class="badge match">${recipe.matchPercent}% match (${recipe.usedIngredientCount}/${recipe.usedIngredientCount + recipe.missedIngredientCount})</span>
    ${recipe.missedIngredientCount > 0 ? `<span class="badge missing">${recipe.missedIngredientCount} missing</span>` : `<span class="badge match">All ingredients on hand</span>`}
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

  const ingredientItems = recipe.scaledIngredients.map(ing => {
    const isStaple = staplesSet.has((ing.name || "").toLowerCase());
    const amount = ing.scaledAmount ?? ing.amount ?? "";
    return `<li class="${isStaple ? "staple" : ""}">${amount} ${ing.unit || ""} ${ing.name || ing.originalName}${isStaple ? " (staple)" : ""}</li>`;
  }).join("");

  const missingForShoppingList = recipe.scaledIngredients.filter(
    ing => !staplesSet.has((ing.name || "").toLowerCase())
  );

  modalBody.innerHTML = `
    <h2>${escapeHtml(recipe.title)}</h2>
    <p>${recipe.readyInMinutes ? `Ready in ${recipe.readyInMinutes} min &middot; ` : ""}Serves ${recipe.requestedServings} (scaled from ${recipe.defaultServings})</p>
    <h3>Ingredients</h3>
    <ul class="ingredient-list">${ingredientItems}</ul>
    <button type="button" id="shopping-list-btn" class="secondary-btn shopping-list-btn">Copy missing-ingredients shopping list</button>
    <h3>Instructions</h3>
    ${renderInstructions(recipe)}
    <h3>Nutrition</h3>
    <div id="nutrition-area"><button type="button" id="load-nutrition-btn" class="secondary-btn">Calculate nutrition for this serving size</button></div>
    ${recipe.sourceUrl ? `<p><a href="${recipe.sourceUrl}" target="_blank" rel="noopener">View original source</a></p>` : ""}
  `;

  document.getElementById("shopping-list-btn").addEventListener("click", () => {
    const list = missingForShoppingList
      .map(ing => `${ing.scaledAmount ?? ing.amount ?? ""} ${ing.unit || ""} ${ing.name || ing.originalName}`.trim())
      .join("\n");
    navigator.clipboard?.writeText(list).catch(() => {});
    alert("Shopping list copied to clipboard:\n\n" + list);
  });

  document.getElementById("load-nutrition-btn").addEventListener("click", () => loadNutrition(recipe));
}

function renderInstructions(recipe) {
  if (recipe.analyzedInstructions && recipe.analyzedInstructions.length) {
    const steps = recipe.analyzedInstructions[0].steps || [];
    if (steps.length) {
      return `<ol class="instructions-list">${steps.map(s => `<li>${escapeHtml(s.step)}</li>`).join("")}</ol>`;
    }
  }
  if (recipe.instructions) {
    return `<div>${recipe.instructions}</div>`;
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

    area.innerHTML = `
      <p>Nutrition per serving</p>
      <div class="nutrition-box">
        ${cal !== null ? `<div><strong>${cal}</strong><br>calories</div>` : ""}
        ${protein !== null ? `<div><strong>${protein}</strong><br>protein</div>` : ""}
        ${fat !== null ? `<div><strong>${fat}</strong><br>fat</div>` : ""}
        ${carbs !== null ? `<div><strong>${carbs}</strong><br>carbs</div>` : ""}
      </div>
      ${data.cached ? '<p style="font-size:0.8rem;color:var(--muted)">(from cache)</p>' : ""}
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
    card.innerHTML = `
      <img src="${f.image || ""}" alt="${escapeHtml(f.title)}">
      <div class="recipe-card-body">
        <h3>${escapeHtml(f.title)}</h3>
      </div>
    `;
    card.addEventListener("click", () => openRecipeModal(f.recipe_id, 4));
    grid.appendChild(card);
  });
}

// ---------- Utils ----------

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
