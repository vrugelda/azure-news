"use strict";

const STATUS_LABELS = {
  ga: "Generally available",
  preview: "Preview",
  retirement: "Retirement",
  announcement: "Announcement",
  guidance: "Guidance",
};
const ACTION_LABELS = {
  adopt: "Adopt",
  evaluate: "Evaluate",
  "plan-migration": "Plan migration",
  "be-aware": "Be aware",
};
const PILLAR_LABELS = {
  reliability: "Reliability",
  security: "Security",
  cost: "Cost",
  operations: "Operations",
  performance: "Performance",
};

const state = { items: [], statuses: new Set(), pillars: new Set(), query: "", details: false };

const listEl = document.getElementById("list");
const noticeEl = document.getElementById("notice");
const metaEl = document.getElementById("meta");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDate(iso, options) {
  return new Date(iso).toLocaleDateString(undefined, options);
}

function renderChips(containerId, labels, selected) {
  const container = document.getElementById(containerId);
  const present = new Set(
    state.items.flatMap((item) => (containerId === "status-chips" ? [item.status] : item.pillars))
  );
  container.replaceChildren();
  for (const [value, label] of Object.entries(labels)) {
    if (!present.has(value)) continue;
    const chip = el("button", "chip", label);
    chip.type = "button";
    chip.setAttribute("aria-pressed", "false");
    chip.addEventListener("click", () => {
      const on = !selected.has(value);
      on ? selected.add(value) : selected.delete(value);
      chip.setAttribute("aria-pressed", String(on));
      renderList();
    });
    container.append(chip);
  }
}

function renderDetailsToggle() {
  const smaller = state.items.filter((item) => item.tier === "detail").length;
  const chip = document.getElementById("details-toggle");
  chip.hidden = smaller === 0;
  chip.textContent = `Include ${smaller} smaller update${smaller === 1 ? "" : "s"}`;
  chip.addEventListener("click", () => {
    state.details = !state.details;
    chip.setAttribute("aria-pressed", String(state.details));
    renderList();
  });
}

function matches(item) {
  if (item.tier === "detail" && !state.details) return false;
  if (state.statuses.size && !state.statuses.has(item.status)) return false;
  if (state.pillars.size && !item.pillars.some((p) => state.pillars.has(p))) return false;
  if (!state.query) return true;
  const haystack = [item.headline, item.summary, item.architecture_impact, ...item.services]
    .join(" ")
    .toLowerCase();
  return state.query.split(/\s+/).every((word) => haystack.includes(word));
}

function renderCard(item) {
  const card = el("article", "card");

  const top = el("div", "card-top");
  top.append(el("span", `status status-${item.status}`, STATUS_LABELS[item.status] || item.status));
  top.append(el("span", "", formatDate(item.published, { day: "numeric", month: "short" })));
  const importance = el("span", "importance");
  importance.title = `Importance ${item.importance} of 5`;
  importance.setAttribute("aria-label", importance.title);
  for (let i = 1; i <= 5; i++) importance.append(el("span", i <= item.importance ? "on" : ""));
  top.append(importance);

  const foot = el("div", "card-foot");
  foot.append(el("span", "tag action", ACTION_LABELS[item.recommended_action] || item.recommended_action));
  const more = el("button", "more", "Details");
  more.type = "button";
  more.setAttribute("aria-expanded", "false");
  foot.append(more);

  const details = el("div", "details");
  details.append(el("p", "", item.summary));
  if (item.architecture_impact) {
    const impact = el("p", "impact");
    impact.append(el("span", "label", "Architecture impact"), item.architecture_impact);
    details.append(impact);
  }
  const tags = el("div", "tags");
  for (const service of item.services) tags.append(el("span", "tag", service));
  for (const pillar of item.pillars) tags.append(el("span", "tag", PILLAR_LABELS[pillar] || pillar));
  if (tags.childElementCount) details.append(tags);
  if (/^https?:\/\//.test(item.link)) {
    const link = el("a", "source", `Read at ${item.source_name} \u2197`);
    link.href = item.link;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    details.append(link);
  }

  card.append(top, el("h2", "", item.headline), foot, details);
  // Hovering previews the details (CSS); clicking pins the card open at full width.
  card.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    const open = card.classList.toggle("open");
    more.setAttribute("aria-expanded", String(open));
    more.textContent = open ? "Close" : "Details";
  });
  return card;
}

function renderGrid(items) {
  const grid = el("div", "grid");
  grid.append(...items.map(renderCard));
  return grid;
}

function renderList() {
  const visible = state.items.filter(matches);
  const guidance = visible.filter((item) => item.status === "guidance");
  const nodes = [];
  if (guidance.length) {
    nodes.push(el("h3", "section", "Architecture guidance"), renderGrid(guidance));
  }
  const months = new Map();
  for (const item of visible) {
    if (item.status === "guidance") continue;
    const month = formatDate(item.published, { month: "long", year: "numeric" });
    if (!months.has(month)) months.set(month, []);
    months.get(month).push(item);
  }
  for (const [month, items] of months) {
    nodes.push(el("h3", "section", `Platform changes \u00b7 ${month}`), renderGrid(items));
  }
  listEl.replaceChildren(...nodes);

  noticeEl.hidden = visible.length > 0;
  if (!visible.length) {
    noticeEl.textContent = state.items.length
      ? "No updates match these filters."
      : "No updates yet.";
  }
}

async function load() {
  try {
    const response = await fetch("data/news.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.items = data.items;
    const major = data.items.filter((item) => item.tier !== "detail").length;
    const count = `${major} major item${major === 1 ? "" : "s"}`;
    metaEl.textContent = data.updated_at
      ? `${count} · refreshed ${new Date(data.updated_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`
      : count;
    renderChips("status-chips", STATUS_LABELS, state.statuses);
    renderChips("pillar-chips", PILLAR_LABELS, state.pillars);
    renderDetailsToggle();
    renderList();
  } catch (error) {
    metaEl.textContent = "";
    noticeEl.hidden = false;
    noticeEl.textContent = `Could not load updates (${error.message}).`;
  }
}

document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  renderList();
});

// Scrolling about five wheel notches closes any hover preview; it can return once the
// pointer moves again.
const SCROLL_DISMISS_PX = 450;
let scrollStart = window.scrollY;
window.addEventListener(
  "scroll",
  () => {
    if (Math.abs(window.scrollY - scrollStart) >= SCROLL_DISMISS_PX) {
      document.documentElement.classList.add("no-preview");
    }
  },
  { passive: true }
);
window.addEventListener("mousemove", () => {
  scrollStart = window.scrollY;
  document.documentElement.classList.remove("no-preview");
});

load();
