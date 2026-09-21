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

function renderRoomTimes(root = document) {
  root.querySelectorAll("time[data-epoch-ms]").forEach((node) => {
    const value = Number(node.dataset.epochMs);
    if (!Number.isFinite(value)) return;
    const date = new Date(value);
    node.textContent = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    }).format(date);
    node.dateTime = date.toISOString();
  });
}

renderRoomTimes();
document.body.addEventListener("htmx:afterSwap", (event) => {
  renderRoomTimes(event.detail.target || document);
});
