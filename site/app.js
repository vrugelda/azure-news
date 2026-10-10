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

const state = { items: [], statuses: new Set(), pillars: new Set(), query: "" };

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

function matches(item) {
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
  top.append(el("span", "", item.source_name));
  const importance = el("span", "importance");
  importance.title = `Importance ${item.importance} of 5`;
  importance.setAttribute("aria-label", importance.title);
  for (let i = 1; i <= 5; i++) importance.append(el("span", i <= item.importance ? "on" : ""));
  top.append(importance);
  card.append(top);

  const heading = el("h2");
  if (/^https?:\/\//.test(item.link)) {
    const link = el("a", "", item.headline);
    link.href = item.link;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    heading.append(link);
  } else {
    heading.textContent = item.headline;
  }
  card.append(heading);
  card.append(el("p", "", item.summary));

  if (item.architecture_impact) {
    const impact = el("p", "impact");
    impact.append(el("span", "label", "Architecture impact"), item.architecture_impact);
    card.append(impact);
  }

  const bottom = el("div", "card-bottom");
  bottom.append(el("span", "tag action", ACTION_LABELS[item.recommended_action] || item.recommended_action));
  for (const service of item.services) bottom.append(el("span", "tag", service));
  for (const pillar of item.pillars) bottom.append(el("span", "tag", PILLAR_LABELS[pillar] || pillar));
  card.append(bottom);
  return card;
}

function renderList() {
  const visible = state.items.filter(matches);
  const nodes = [];
  let month = "";
  for (const item of visible) {
    const itemMonth = formatDate(item.published, { month: "long", year: "numeric" });
    if (itemMonth !== month) {
      month = itemMonth;
      nodes.push(el("h3", "month", month));
    }
    nodes.push(renderCard(item));
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
    const count = `${data.items.length} update${data.items.length === 1 ? "" : "s"}`;
    metaEl.textContent = data.updated_at
      ? `${count} · refreshed ${new Date(data.updated_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`
      : count;
    renderChips("status-chips", STATUS_LABELS, state.statuses);
    renderChips("pillar-chips", PILLAR_LABELS, state.pillars);
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

load();
