// AI Engineering Radar - shared frontend logic
// Reads pre-generated JSON from data/ and renders it client-side.

const SECTION_ORDER = [
  "for_you",
  "top_stories",
  "model_tooling",
  "robotics_vla",
  "vlm_multimodal",
  "papers",
  "repos",
  "industry",
];

async function fetchJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function renderItem(item) {
  const tags = (item.tags || [])
    .map((t) => `<span class="tag">${escapeHTML(t)}</span>`)
    .join("");
  const reportedBy = item.also_reported_by && item.also_reported_by.length
    ? ` (also: ${item.also_reported_by.map(escapeHTML).join(", ")})`
    : "";
  const personalBadge = item.personal_match
    ? '<span class="tag tag-personal">★ matches your stack</span>'
    : "";
  return `
    <article class="item" data-tags="${escapeHTML((item.tags || []).join(" "))}" data-category="${escapeHTML(item.category || "")}">
      ${personalBadge}
      <h3><a href="${escapeHTML(item.url)}" target="_blank" rel="noopener">${escapeHTML(item.title)}</a></h3>
      <p class="item-meta">${escapeHTML(item.source)}${reportedBy} · ${escapeHTML(formatDate(item.published_at))} · score ${Number(item.score).toFixed(2)}</p>
      <p class="item-summary">${escapeHTML(item.summary)}</p>
      <p class="item-why"><strong>Why it matters:</strong> ${escapeHTML(item.why_it_matters)}</p>
      <p class="item-tags">${tags}</p>
    </article>
  `;
}

function renderSection(section) {
  const items = section.items && section.items.length
    ? section.items.map(renderItem).join("")
    : '<p class="empty">No items today.</p>';
  return `
    <section class="digest-section" data-section="${escapeHTML(section.id)}">
      <h2>${escapeHTML(section.name)}</h2>
      ${items}
    </section>
  `;
}

function orderSections(sections) {
  const byId = Object.fromEntries(sections.map((s) => [s.id, s]));
  return SECTION_ORDER.map((id) => byId[id]).filter(Boolean);
}

function renderDigest(digest, root) {
  const headlineEl = root.querySelector("[data-headline]");
  const metaEl = root.querySelector("[data-meta]");
  const summaryEl = root.querySelector("[data-summary]");
  const sectionsEl = root.querySelector("[data-sections]");

  if (headlineEl) headlineEl.textContent = digest.headline;
  if (metaEl) metaEl.textContent = `Generated ${formatDate(digest.generated_at)}`;
  if (summaryEl) summaryEl.textContent = digest.summary;
  if (sectionsEl) {
    const sections = orderSections(digest.sections);
    sectionsEl.innerHTML = sections.map(renderSection).join("");
  }
}

function setupFilters(root) {
  const filterBar = root.querySelector("[data-filters]");
  const sectionsEl = root.querySelector("[data-sections]");
  if (!filterBar || !sectionsEl) return;

  filterBar.addEventListener("click", (e) => {
    const btn = e.target.closest(".filter-btn");
    if (!btn) return;
    filterBar.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    const filter = btn.dataset.filter;
    sectionsEl.querySelectorAll(".digest-section").forEach((sec) => {
      if (filter === "all" || sec.dataset.section === filter) {
        sec.style.display = "";
      } else {
        sec.style.display = "none";
      }
    });
  });
}

window.AIRadar = {
  fetchJSON,
  renderDigest,
  renderSection,
  renderItem,
  setupFilters,
  formatDate,
  escapeHTML,
};
