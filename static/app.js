// Finanzwabe: small enhancements. Every page also works without JavaScript.
"use strict";

// --- Offline support and installation (PWA) ------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

let installPrompt = null;
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  const card = document.getElementById("install-card");
  if (card) card.classList.add("visible");
});

document.addEventListener("click", async (event) => {
  if (!event.target.closest("#install-button") || !installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  document.getElementById("install-card")?.classList.remove("visible");
});

// --- Confirm before deleting -----------------------------------------------------
document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

document.addEventListener("DOMContentLoaded", () => {
  setupBookingForm();
  setupAccountForm();
  setupCategoryForm();
});

// --- Booking form: filter categories by kind, show transfer target, suggestions ---
function setupBookingForm() {
  const select = document.querySelector("[data-category-select]");
  if (!select) return;
  const form = select.form;
  const groups = Array.from(select.querySelectorAll("optgroup"));
  const placeholder = select.querySelector("option[value='']");
  const transferOnly = form.querySelector("[data-transfer-only]");
  const accountLabel = form.querySelector("[data-account-label]");
  const description = form.querySelector("#description");
  const suggestions = JSON.parse(document.getElementById("suggestions")?.textContent || "{}");
  const lowerSuggestions = new Map(
    Object.entries(suggestions).map(([text, id]) => [text.toLowerCase(), String(id)])
  );

  const currentKind = () => form.querySelector("input[name='kind']:checked")?.value || "expense";

  function kindOfCategory(id) {
    const group = groups.find((g) => g.querySelector(`option[value='${id}']`));
    return group ? group.dataset.kind : null;
  }

  function applyKind(kind) {
    const selected = select.value;
    select.replaceChildren(placeholder, ...groups.filter((g) => g.dataset.kind === kind));
    select.value = kindOfCategory(selected) === kind ? selected : "";
    const isTransfer = kind === "transfer";
    if (transferOnly) transferOnly.hidden = !isTransfer;
    if (accountLabel) accountLabel.textContent = isTransfer ? accountLabel.dataset.transfer : accountLabel.dataset.default;
  }

  function setKind(kind) {
    const radio = form.querySelector(`input[name='kind'][value='${kind}']`);
    if (radio && !radio.checked) {
      radio.checked = true;
      applyKind(kind);
    }
  }

  form.querySelectorAll("input[name='kind']").forEach((radio) =>
    radio.addEventListener("change", () => applyKind(radio.value))
  );

  // Picking a category from another kind is not possible any more, but a
  // suggestion may switch the kind: "Gehalt" selects Einnahme automatically.
  if (description) {
    description.addEventListener("change", () => {
      const id = lowerSuggestions.get(description.value.trim().toLowerCase());
      if (!id) return;
      const kind = kindOfCategory(id);
      if (kind) setKind(kind);
      select.value = id;
    });
  }

  const initialKind = kindOfCategory(select.value) || currentKind();
  setKind(initialKind);
  applyKind(initialKind);
}

// --- Account form: credit limit only for credit cards ---------------------------------
function setupAccountForm() {
  const type = document.querySelector("[data-account-type]");
  const limit = document.querySelector("[data-credit-only]");
  if (!type || !limit) return;
  const update = () => { limit.hidden = type.value !== "credit_card"; };
  type.addEventListener("change", update);
  update();
}

// --- Category form: fixed costs and budget only for expenses ------------------------
function setupCategoryForm() {
  const switcher = document.querySelector("[data-category-kind]");
  const expenseOnly = document.querySelector("[data-expense-only]");
  if (!switcher || !expenseOnly) return;
  const update = () => {
    const checked = switcher.querySelector("input:checked");
    expenseOnly.hidden = checked ? checked.value !== "expense" : false;
  };
  switcher.addEventListener("change", update);
  update();
}
