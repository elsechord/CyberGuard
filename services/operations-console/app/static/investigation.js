"use strict";

// Enhance ordinary fragment links; source text remains available without JS.
function revealInvestigationMaterial() {
  const target = document.getElementById(window.location.hash.slice(1));
  if (!target || !target.matches("details.investigation-material")) return;
  target.open = true;
  target.scrollIntoView({ block: "start" });
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-material-link]");
  if (!link) return;
  const target = document.getElementById(link.getAttribute("href").slice(1));
  if (target && target.matches("details.investigation-material")) target.open = true;
});
window.addEventListener("hashchange", revealInvestigationMaterial);
revealInvestigationMaterial();
