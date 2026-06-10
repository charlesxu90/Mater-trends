/* Mater-trend static browser. Vanilla JS, no build step.
   Loads data/manifest.json + data/trends.json; lazy-loads per (journal, year)
   paper shards on demand so any year is browsable without preloading the corpus. */

const DATA = "data/";
const PAGE = 20;
const BUCKET_LABELS = { year: "Year", quarter: "Quarter", month: "Month" };

// A pinned topic kept permanently visible at the bottom of Topic Trends, with its
// own paper-count series — for a research focus the user tracks frequently.
const HIGHLIGHT_TOPIC = "regenerative medicine";

const state = {
  manifest: null,
  trends: {},            // { bucket: [ {group, period, top, emerging, fading, counts}, ... ] }
  bucket: "year",        // selected trend granularity (default: year)
  group: null,           // selected journal in the trends view
  period: null,          // selected trend period (e.g. "2025", "2025-Q2", "2025-06")
  journalRank: {},       // journal label -> impact-factor rank (0 = highest)
  shardCache: {},        // shard file -> records[]
  loaded: [],            // records currently loaded for the active period/journal
  shown: PAGE,
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

async function getJSON(path) {
  const resp = await fetch(DATA + path);
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

// ---- init -------------------------------------------------------------------
async function init() {
  try {
    [state.manifest, state.trends] = await Promise.all([
      getJSON("manifest.json"),
      getJSON("trends.json"),
    ]);
  } catch (err) {
    $("#trend-panel").innerHTML = `<p class="loading">Could not load data (${err.message}). Run <code>mat-trend refresh</code> first.</p>`;
    return;
  }
  state.manifest.journals.forEach((j, i) => { state.journalRank[j.label] = i; });
  buildHeroStats();
  buildBucketPicker();
  buildTrendPicker();
  buildFilters();
  initSideNav();
  await applyBrowse();
}

// Right-side fast nav: highlight the section currently in view.
function initSideNav() {
  const links = [...document.querySelectorAll(".sidenav a")];
  const byTarget = Object.fromEntries(links.map((a) => [a.dataset.target, a]));
  const sections = [
    ["top", document.querySelector(".hero")],
    ["trends", document.getElementById("trends")],
    ["browse", document.getElementById("browse")],
  ].filter(([, node]) => node);
  const obs = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const id = sections.find(([, node]) => node === e.target)?.[0];
        if (id && byTarget[id]) links.forEach((a) => a.classList.toggle("active", a === byTarget[id]));
      }
    },
    { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
  );
  sections.forEach(([, node]) => obs.observe(node));
}

function byRank(a, b) {
  const ra = state.journalRank[a] ?? 999;
  const rb = state.journalRank[b] ?? 999;
  return ra === rb ? a.localeCompare(b) : ra - rb;
}

// ---- hero -------------------------------------------------------------------
function buildHeroStats() {
  const m = state.manifest;
  const total = m.total_articles ?? m.shards.reduce((s, x) => s + x.count, 0);
  const years = m.trend_years || [];
  const yearsLabel = years.length > 1 ? `years (${years[0]}–${years[years.length - 1]})` : "years";
  const stats = [
    [m.journals.length, "journals"],
    [total.toLocaleString(), "articles"],
    [m.taxonomy_topics ?? m.topics.length, "topics"],
    [years.length || m.years.length, yearsLabel],
  ];
  const box = $("#hero-stats");
  for (const [num, label] of stats) {
    const s = el("div", "stat");
    s.append(el("div", "stat__num", String(num)), el("div", "stat__label", label));
    box.append(s);
  }
}

// ---- trends -----------------------------------------------------------------
function currentTrends() {
  return state.trends[state.bucket] || [];
}

function buildBucketPicker() {
  const buckets = (state.manifest.buckets || ["year", "quarter", "month"])
    .filter((b) => (state.trends[b] || []).length);
  const row = $("#bucket-pills");
  row.innerHTML = "";
  for (const b of buckets) {
    const pill = el("button", "pill", BUCKET_LABELS[b] || b);
    pill.type = "button";
    pill.dataset.bucket = b;
    pill.addEventListener("click", () => selectBucket(b));
    row.append(pill);
  }
  state.bucket = buckets.includes("year") ? "year" : buckets[0];
}

function selectBucket(bucket) {
  state.bucket = bucket;
  for (const p of $("#bucket-pills").children)
    p.setAttribute("aria-pressed", String(p.dataset.bucket === bucket));
  $("#period-label").textContent = BUCKET_LABELS[bucket] || "Period";
  buildTrendPicker();
}

function buildTrendPicker() {
  for (const p of $("#bucket-pills").children)
    p.setAttribute("aria-pressed", String(p.dataset.bucket === state.bucket));
  $("#period-label").textContent = BUCKET_LABELS[state.bucket] || "Period";

  // journals ordered by impact factor (manifest order), not alphabetical
  const groups = [...new Set(currentTrends().map((t) => t.group))].sort(byRank);
  const row = $("#group-pills");
  row.innerHTML = "";
  groups.forEach((g) => {
    const pill = el("button", "pill pill--journal", g);
    pill.type = "button";
    pill.addEventListener("click", () => selectGroup(g));
    row.append(pill);
  });
  const group = groups.includes(state.group) ? state.group : groups[0];
  if (group) selectGroup(group);
}

function selectGroup(group) {
  state.group = group;
  for (const p of $("#group-pills").children)
    p.setAttribute("aria-pressed", String(p.textContent === group));

  const periods = currentTrends()
    .filter((t) => t.group === group)
    .map((t) => t.period)
    .sort()
    .reverse(); // recent → old, left to right
  const row = $("#period-pills");
  row.innerHTML = "";
  periods.forEach((per) => {
    const pill = el("button", "pill", per);
    pill.type = "button";
    pill.addEventListener("click", () => selectPeriod(per));
    row.append(pill);
  });
  if (periods.length) selectPeriod(periods[0]); // default: most recent
}

function selectPeriod(period) {
  state.period = period;
  for (const p of $("#period-pills").children)
    p.setAttribute("aria-pressed", String(p.textContent === period));
  renderTrend();
}

function renderTrend() {
  const t = currentTrends().find((x) => x.group === state.group && x.period === state.period);
  const panel = $("#trend-panel");
  panel.innerHTML = "";
  renderHighlight();
  if (!t) { panel.append(el("p", "empty", "No trend data.")); return; }

  const cols = el("div", "cols");
  cols.append(
    trendCol("top", "Top", t.top),
    trendCol("emerging", "Emerging" + (t.previous_period ? "" : " —"), t.emerging),
    trendCol("fading", "Fading", t.fading),
  );
  const baseline = t.previous_period ? ` vs ${t.previous_period}` : " (no prior period)";
  const left = el("div");
  left.append(cols, el("p", "result-meta", `${t.group} · ${t.period}${baseline}`));
  panel.append(left, renderChart(t.counts || {}));
}

// Pinned topic strip: current count for the selected journal+period, plus a
// per-period series across the current bucket so the trajectory is always visible.
function renderHighlight() {
  const host = $("#topic-highlight");
  host.innerHTML = "";
  const rows = currentTrends().filter((x) => x.group === state.group);
  if (!rows.length) { host.hidden = true; return; }
  host.hidden = false;

  const series = rows
    .map((x) => ({ period: x.period, n: (x.counts && x.counts[HIGHLIGHT_TOPIC]) || 0 }))
    .sort((a, b) => a.period.localeCompare(b.period)); // chronological: old → recent
  const current = series.find((s) => s.period === state.period);
  const currentN = current ? current.n : 0;
  const max = series.reduce((m, s) => Math.max(m, s.n), 0);

  // Lead: pin label, clickable topic name, scope, big current count.
  const lead = el("div", "highlight__lead");
  const name = el("button", "highlight__name", HIGHLIGHT_TOPIC);
  name.type = "button";
  name.title = `Browse ${HIGHLIGHT_TOPIC} papers`;
  name.addEventListener("click", () => jumpToTopic(HIGHLIGHT_TOPIC));
  const big = el("p", "highlight__count");
  big.append(
    el("span", "highlight__num", currentN.toLocaleString()),
    el("span", "highlight__unit", currentN === 1 ? "paper" : "papers"),
  );
  lead.append(
    el("p", "highlight__pin", "★ Pinned topic"),
    name,
    el("p", "highlight__scope", `${state.group} · ${state.period}`),
    big,
  );

  // Series: one bar per period of the current bucket (selected journal).
  const chart = el("div", "highlight__series");
  chart.append(el("p", "highlight__series-h", `By ${(BUCKET_LABELS[state.bucket] || "period").toLowerCase()}`));
  const bars = el("div", "highlight__bars");
  for (const s of series) {
    const bar = el("button", "hbar" + (s.period === state.period ? " hbar--active" : ""));
    bar.type = "button";
    bar.title = `${s.n} ${HIGHLIGHT_TOPIC} paper${s.n === 1 ? "" : "s"} in ${s.period}`;
    bar.addEventListener("click", () => selectPeriod(s.period));
    const track = el("div", "hbar__track");
    const fill = el("div", "hbar__fill");
    fill.style.height = `${max ? Math.max(3, (s.n / max) * 100) : 0}%`;
    track.append(fill);
    bar.append(el("span", "hbar__val", String(s.n)), track, el("span", "hbar__lbl", s.period));
    bars.append(bar);
  }
  chart.append(bars);

  host.append(lead, chart);
}

function trendCol(kind, heading, topics) {
  const col = el("div", `col col--${kind}`);
  col.append(el("h3", "col__h", heading));
  if (!topics.length) { col.append(el("p", "empty", "—")); return col; }
  const ol = el("ol", "rank");
  for (const name of topics) {
    const chip = el("button", "chip");
    chip.type = "button";
    chip.title = `Browse ${name} papers`;
    chip.addEventListener("click", () => jumpToTopic(name));
    chip.append(el("span", "chip__rank"), el("span", "chip__name", name));
    const li = el("li");
    li.append(chip);
    ol.append(li);
  }
  col.append(ol);
  return col;
}

function renderChart(counts) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12);
  const chart = el("div", "chart");
  chart.append(el("p", "chart__h", "Most papers"));
  if (!entries.length) { chart.append(el("p", "empty", "No counts.")); return chart; }
  const max = entries[0][1];
  for (const [name, val] of entries) {
    const bar = el("button", "bar");
    bar.type = "button";
    bar.title = `Browse ${name}`;
    bar.addEventListener("click", () => jumpToTopic(name));
    const track = el("div", "bar__track");
    const fill = el("div", "bar__fill");
    fill.style.width = `${Math.max(2, (val / max) * 100)}%`;
    track.append(fill);
    bar.append(el("span", "bar__name", name), track, el("span", "bar__val", String(val)));
    chart.append(bar);
  }
  return chart;
}

// Click a topic in the trends -> drill into the Rising Stars list for the SAME
// journal + period the trend is showing, filtered to that topic (matches AI-trend).
async function jumpToTopic(topic) {
  $("#f-journal").value = state.group || "";   // the journal selected in the trends
  $("#f-topic").value = topic;
  setPeriodValue(state.period);
  state.shown = PAGE;
  $("#browse").scrollIntoView({ behavior: "smooth" });
  await applyBrowse();
}

// ---- browse (lazy-loaded) ---------------------------------------------------
function buildFilters() {
  const m = state.manifest;
  // journals in impact-factor order
  for (const j of m.journals) $("#f-journal").append(new Option(j.label, j.label));
  // period: years first (default latest), then months
  const years = (m.years || []).slice().reverse();
  const months = (m.periods || []).slice().reverse();
  const sel = $("#f-period");
  for (const y of years) sel.append(new Option(`${y} (whole year)`, y));
  for (const mo of months) sel.append(new Option(mo, mo));
  if (years.length) sel.value = years[0]; // default: most recent year
  fillSelect("#f-topic", m.topics);

  for (const id of ["#f-journal", "#f-period", "#f-topic", "#f-sort"])
    $(id).addEventListener("change", onFilterChange);
  $("#f-search").addEventListener("input", debounce(onFilterChange, 200));
  $("#more-btn").addEventListener("click", () => { state.shown += PAGE; renderList(); });
}

function fillSelect(sel, values) {
  const node = $(sel);
  const first = node.options[0];
  node.innerHTML = "";
  if (first) node.append(first);
  for (const v of values) node.append(new Option(v, v));
}

async function onFilterChange() {
  state.shown = PAGE;
  await applyBrowse();
}

// Ensure a period value (possibly a quarter like "2025-Q2" not in the dropdown)
// is selectable, then select it.
function setPeriodValue(value) {
  const sel = $("#f-period");
  if (!value) { sel.value = ""; return; }
  if (![...sel.options].some((o) => o.value === value)) {
    sel.append(new Option(value, value));
  }
  sel.value = value;
}

function periodYears(value) {
  if (!value) return state.manifest.years.slice(); // all browsable years
  return [value.slice(0, 4)];
}

function periodMatch(month, value) {
  if (!value) return true;
  if (/^\d{4}$/.test(value)) return month.slice(0, 4) === value;
  const q = value.match(/^(\d{4})-Q([1-4])$/);
  if (q) {
    const mo = parseInt(month.slice(5, 7), 10);
    const start = (parseInt(q[2], 10) - 1) * 3 + 1;
    return month.slice(0, 4) === q[1] && mo >= start && mo <= start + 2;
  }
  return month === value; // exact YYYY-MM
}

function requiredShardFiles() {
  const years = new Set(periodYears($("#f-period").value));
  const journal = $("#f-journal").value;
  return state.manifest.shards
    .filter((s) => years.has(s.year) && (!journal || s.label === journal))
    .map((s) => s.file);
}

async function ensureLoaded() {
  const files = requiredShardFiles();
  const missing = files.filter((f) => !(f in state.shardCache));
  if (missing.length) {
    const fetched = await Promise.all(
      missing.map((f) => getJSON(f).then((r) => [f, r]).catch(() => [f, []])),
    );
    for (const [f, r] of fetched) state.shardCache[f] = r;
  }
  state.loaded = files.flatMap((f) => state.shardCache[f] || []);
}

async function applyBrowse() {
  $("#result-meta").textContent = "Loading articles…";
  $("#papers").innerHTML = "";
  await ensureLoaded();
  renderList();
}

function currentResults() {
  const journal = $("#f-journal").value;
  const period = $("#f-period").value;
  const topic = $("#f-topic").value;
  const q = $("#f-search").value.trim().toLowerCase();
  const sort = $("#f-sort").value;

  let out = state.loaded.filter((p) => {
    if (journal && p.journal !== journal) return false;
    if (!periodMatch(p.period, period)) return false;
    if (topic && !(p.topics || []).includes(topic)) return false;
    if (q) {
      const hay = (p.title + " " + (p.authors || []).join(" ") + " " + (p.abstract || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (sort === "citations") out.sort((a, b) => (b.citations ?? -1) - (a.citations ?? -1));
  else if (sort === "rising") out.sort((a, b) => (b.rising ?? 0) - (a.rising ?? 0) || (b.citations ?? -1) - (a.citations ?? -1));
  else out.sort((a, b) => (b.published || "").localeCompare(a.published || ""));
  return out;
}

function renderList() {
  const all = currentResults();
  const list = $("#papers");
  list.innerHTML = "";
  const slice = all.slice(0, state.shown);
  for (const p of slice) list.append(paperCard(p));
  $("#result-meta").textContent = all.length
    ? `${all.length.toLocaleString()} article${all.length === 1 ? "" : "s"} — showing ${slice.length}`
    : "No articles match these filters.";
  $("#more-wrap").hidden = state.shown >= all.length;
}

const articleUrl = (p) => p.link || (p.doi ? `https://doi.org/${p.doi}` : null);

function paperCard(p) {
  const li = el("li", "paper");
  const url = articleUrl(p);

  // Row 1: citations (upper-left) | journal · date (upper-right)
  const head = el("div", "paper__head");
  let cites = "";
  if (p.citations != null) cites = `${p.citations.toLocaleString()} cites`;
  if (p.rising) cites += ` · ▲ +${p.rising}`;
  head.append(el("span", "paper__cites", cites));
  head.append(el("span", "paper__venue", `${p.journal} · ${p.period}`));
  li.append(head);

  // Row 2: title, full width, clamped to two lines (CSS adds the ellipsis)
  const h = el("h3", "paper__title");
  if (url) {
    const a = el("a", null, p.title);
    a.href = url; a.target = "_blank"; a.rel = "noopener";
    h.append(a);
  } else {
    h.textContent = p.title;
  }
  li.append(h);

  // Authors on a single line (CSS clips overflow); always render so the row is
  // reserved even when there are no authors.
  const authors = p.authors && p.authors.length ? p.authors.join(", ") : "";
  li.append(el("p", "paper__authors", authors));

  // Topic tags — refine the current list by that topic (keep the journal/period).
  if (p.topics && p.topics.length) {
    const tags = el("div", "tags");
    for (const t of p.topics) {
      const tag = el("button", "tag", t);
      tag.type = "button";
      tag.title = `Filter by ${t}`;
      tag.addEventListener("click", () => { $("#f-topic").value = t; onFilterChange(); });
      tags.append(tag);
    }
    li.append(tags);
  }
  return li;
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

init();
