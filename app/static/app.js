/* Activity Radar dashboard */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

let META = { categories: [], organizations: [], stats: {} };
let ACTIVITIES = [];

const STATUS_LABEL = {
  open: "Open",
  not_yet_open: "Not yet open",
  waitlist: "Waitlist",
  closed: "Closed",
  unknown: "Unknown",
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtDate = (iso) => iso
  ? new Date(iso + (iso.length === 10 ? "T00:00" : "")).toLocaleDateString(undefined,
      { month: "short", day: "numeric", year: "numeric" })
  : "";

function daysUntil(iso) {
  if (!iso) return null;
  // date-only strings parse as UTC midnight; pin to local midnight instead
  const target = new Date(iso.length === 10 ? iso + "T00:00" : iso);
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  return Math.floor((target - midnight) / 86400000);
}

function countdownText(iso) {
  const d = daysUntil(iso);
  if (d === null || d < 0) return "";
  if (d === 0) return "opens today!";
  if (d === 1) return "opens tomorrow";
  return `opens in ${d} days`;
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 3500);
}

/* ---------------- meta + stats ---------------- */

async function loadMeta() {
  META = await api("/api/meta");
  $("#stat-total").textContent = META.stats.total;
  $("#stat-open").textContent = META.stats.open;
  $("#stat-soon").textContent = META.stats.not_yet_open;
  $("#stat-new").textContent = META.stats.new_today;

  const catSel = $("#f-category");
  catSel.length = 1;
  META.categories.forEach((c) => catSel.add(new Option(c, c)));

  const orgSel = $("#f-org");
  orgSel.length = 1;
  META.organizations.forEach((o) => orgSel.add(new Option(o.name, o.id)));
}

/* ---------------- activities ---------------- */

function filterParams() {
  const p = new URLSearchParams();
  const q = $("#f-search").value.trim();
  if (q) p.set("q", q);
  if ($("#f-category").value) p.set("category", $("#f-category").value);
  if ($("#f-status").value) p.set("status", $("#f-status").value);
  if ($("#f-org").value) p.set("organization", $("#f-org").value);
  if ($("#f-free").checked) p.set("free_only", "true");
  const age = $("#f-age").value;
  if (age !== "") p.set("age", age);
  p.set("sort", $("#f-sort").value);
  return p;
}

async function loadActivities() {
  ACTIVITIES = await api("/api/activities?" + filterParams());
  renderCards();
}

function badgeHTML(a) {
  const status = a.registration_status;
  let out = `<span class="badge b-${status}"><span class="dot"></span>${STATUS_LABEL[status]}</span>`;
  if (a.is_new) out += `<span class="badge b-new">★ New today</span>`;
  return out;
}

function cardHTML(a) {
  const cd = a.registration_status === "not_yet_open" && a.registration_opens_at
    ? `<span class="countdown">⏰ ${countdownText(a.registration_opens_at)}</span>` : "";
  const dates = a.start_date
    ? `<span>📅 ${fmtDate(a.start_date)}${a.end_date ? "–" + fmtDate(a.end_date) : ""}</span>` : "";
  const sched = a.schedule_text ? `<span>🕐 ${esc(a.schedule_text)}</span>` : "";
  const ages = a.age_text ? `<span>👧 Ages ${esc(a.age_text)}</span>` : "";
  const price = a.is_free
    ? `<span class="price free">Free</span>`
    : (a.price != null ? `<span class="price">$${a.price}${a.resident_pricing ? "*" : ""}</span>`
                       : `<span class="price"></span>`);
  return `
  <article class="card" data-id="${a.id}">
    <div class="card-top">
      <div><h3>${esc(a.name)}</h3><div class="org">${esc(a.organization)}</div></div>
    </div>
    <div class="badges">${badgeHTML(a)}<span class="badge b-cat">${esc(a.category)}</span></div>
    ${a.description ? `<p class="desc">${esc(a.description)}</p>` : ""}
    <div class="meta">${ages}${dates}${sched}${cd}</div>
    <div class="card-foot">
      ${price}
      ${a.signup_url ? `<a class="signup-link" href="${esc(a.signup_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Sign up ↗</a>` : ""}
    </div>
  </article>`;
}

function renderCards() {
  $("#result-count").textContent =
    `${ACTIVITIES.length} activit${ACTIVITIES.length === 1 ? "y" : "ies"}`;
  $("#cards").innerHTML = ACTIVITIES.length
    ? ACTIVITIES.map(cardHTML).join("")
    : `<p class="empty">No activities match these filters.</p>`;
}

/* ---------------- detail modal ---------------- */

const EVENT_LABEL = {
  first_seen: "First appeared in a scrape",
  status_change: "Status changed",
  reg_opened: "Registration opened",
  reg_opening_soon: "Flagged: opening within 48h",
  details_changed: "Details changed",
};

async function openDetail(id) {
  const a = await api(`/api/activities/${id}`);
  const rows = [
    ["Status", `${STATUS_LABEL[a.registration_status]}${a.registration_status === "not_yet_open" && a.registration_opens_at ? " — " + countdownText(a.registration_opens_at) : ""}`],
    ["Reg. opens", a.registration_opens_at ? fmtDate(a.registration_opens_at) : ""],
    ["Ages", a.age_text],
    ["Price", a.is_free ? "Free" : (a.price_text || (a.price != null ? "$" + a.price : ""))],
    ["Dates", a.start_date ? `${fmtDate(a.start_date)}${a.end_date ? " – " + fmtDate(a.end_date) : ""}` : ""],
    ["Schedule", a.schedule_text],
    ["Location", a.location],
    ["Category", a.category],
    ["First seen", fmtDate(a.first_seen_at)],
    ["Last scraped", fmtDate(a.last_scraped_at)],
  ].filter(([, v]) => v);

  $("#modal-body").innerHTML = `
    <h2>${esc(a.name)}</h2>
    <div class="org">${esc(a.organization)}</div>
    <div class="badges">${badgeHTML(a)}<span class="badge b-cat">${esc(a.category)}</span></div>
    ${a.description ? `<p class="desc-full">${esc(a.description)}</p>` : ""}
    <dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <div class="history">
      <h3>Signup history</h3>
      <ul>${a.events.map((e) => `
        <li><span class="when">${fmtDate(e.at)}</span>
            <span>${EVENT_LABEL[e.type] || e.type}${e.old ? ` (${esc(e.old)} → ${esc(e.new)})` : e.new ? `: ${esc(e.new)}` : ""}</span></li>`).join("")}
      </ul>
    </div>
    <div class="modal-actions">
      ${a.signup_url ? `<a class="btn btn-primary" href="${esc(a.signup_url)}" target="_blank" rel="noopener">Go to signup page ↗</a>` : ""}
    </div>`;
  $("#modal").hidden = false;
}

/* ---------------- upcoming tab ---------------- */

async function loadUpcoming() {
  const acts = await api("/api/activities?status=not_yet_open&sort=reg_opens&limit=200");
  const withDate = acts.filter((a) => a.registration_opens_at);
  const noDate = acts.filter((a) => !a.registration_opens_at);

  const groups = new Map();
  withDate.forEach((a) => {
    const key = a.registration_opens_at.slice(0, 10);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(a);
  });

  let html = "";
  for (const [day, items] of groups) {
    const rel = countdownText(day);
    html += `<div class="up-group">
      <div class="up-date">${fmtDate(day)} <span class="rel">${rel}</span></div>
      ${items.map((a) => `
        <div class="up-item" data-id="${a.id}">
          <div class="up-main"><b>${esc(a.name)}</b><small>${esc(a.organization)} · ${esc(a.category)}${a.age_text ? " · ages " + esc(a.age_text) : ""}</small></div>
          ${a.signup_url ? `<a class="signup-link" href="${esc(a.signup_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Signup page ↗</a>` : ""}
        </div>`).join("")}
    </div>`;
  }
  if (noDate.length) {
    html += `<div class="up-group"><div class="up-date">Open date not yet announced</div>
      ${noDate.map((a) => `
        <div class="up-item" data-id="${a.id}">
          <div class="up-main"><b>${esc(a.name)}</b><small>${esc(a.organization)} · ${esc(a.category)}</small></div>
        </div>`).join("")}</div>`;
  }
  $("#upcoming-list").innerHTML = html || `<p class="empty">Nothing pending — all known registrations are open or closed.</p>`;
}

/* ---------------- sources & logs tab ---------------- */

async function loadSources() {
  const sources = await api("/api/sources");
  $("#src-rows").innerHTML = sources.map((s) => `
    <tr>
      <td><input type="checkbox" class="switch src-toggle" data-id="${s.id}" ${s.active ? "checked" : ""}></td>
      <td><a href="${esc(s.homepage_url || s.catalog_url)}" target="_blank" rel="noopener">${esc(s.name)}</a></td>
      <td>${esc(s.platform)}</td>
      <td>${s.activity_count}</td>
      <td>${s.last_scrape_at ? fmtDate(s.last_scrape_at) : "never"}</td>
      <td>${s.last_status
        ? `<span class="${s.last_status}-pill">${s.last_status}</span>${s.error_count ? ` ×${s.error_count}` : ""}`
        : "—"}</td>
      <td><button class="btn btn-sm src-scrape" data-id="${s.id}">Scrape</button></td>
    </tr>`).join("");

  const logs = await api("/api/logs?limit=60");
  $("#log-rows").innerHTML = logs.length ? logs.map((l) => `
    <tr>
      <td>${new Date(l.started_at).toLocaleString()}</td>
      <td>${esc(l.source)}</td>
      <td><span class="${l.status}-pill">${l.status}</span></td>
      <td>${l.found}</td><td>${l.rejected || 0}</td><td>${l.new}</td><td>${l.changed}</td>
      <td class="err" title="${esc([l.error, l.rejection_summary].filter(Boolean).join("\n"))}">${esc((l.error || l.rejection_summary || (l.staling_skipped ? "Stale update skipped for safety" : "")).split("\n")[0])}</td>
    </tr>`).join("")
    : `<tr><td colspan="8" class="empty">No scrapes yet — hit “Scrape now”.</td></tr>`;
}

/* ---------------- settings tab ---------------- */

async function loadSettings() {
  const s = await api("/api/settings");
  $("#s-zip").value = s.zip;
  $("#zip-label").textContent = s.zip;
  $("#s-radius").value = s.radius_minutes;
  $("#s-notify-new").checked = s.notify_new;
  $("#s-notify-opened").checked = s.notify_reg_opened;
  $("#s-notify-soon").checked = s.notify_opening_soon;
  $("#s-digest").checked = s.daily_digest;

  $("#s-mute-cats").innerHTML = META.categories.map((c) => `
    <label class="f-check"><input type="checkbox" class="mute-cat" value="${esc(c)}"
      ${s.muted_categories.includes(c) ? "checked" : ""}> ${esc(c)}</label>`).join("");
  $("#s-mute-orgs").innerHTML = META.organizations.map((o) => `
    <label class="f-check"><input type="checkbox" class="mute-org" value="${o.id}"
      ${s.muted_sources.includes(o.id) ? "checked" : ""}> ${esc(o.name)}</label>`).join("");
}

async function saveSettings() {
  const payload = {
    zip: $("#s-zip").value.trim() || "55113",
    radius_minutes: parseInt($("#s-radius").value, 10) || 15,
    notify_new: $("#s-notify-new").checked,
    notify_reg_opened: $("#s-notify-opened").checked,
    notify_opening_soon: $("#s-notify-soon").checked,
    daily_digest: $("#s-digest").checked,
    muted_categories: $$(".mute-cat:checked").map((el) => el.value),
    muted_sources: $$(".mute-org:checked").map((el) => parseInt(el.value, 10)),
  };
  await api("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("#zip-label").textContent = payload.zip;
  $("#s-saved").hidden = false;
  setTimeout(() => { $("#s-saved").hidden = true; }, 2500);
}

/* ---------------- wiring ---------------- */

function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => { p.hidden = p.id !== "tab-" + name; });
  if (name === "upcoming") loadUpcoming();
  if (name === "sources") loadSources();
  if (name === "settings") loadSettings();
}

document.addEventListener("click", (ev) => {
  const tab = ev.target.closest(".tab");
  if (tab) return showTab(tab.dataset.tab);

  const card = ev.target.closest(".card, .up-item");
  if (card && !ev.target.closest("a")) return openDetail(card.dataset.id);

  if (ev.target.id === "modal-close" || ev.target.id === "modal") $("#modal").hidden = true;

  const scrapeBtn = ev.target.closest(".src-scrape");
  if (scrapeBtn) {
    api(`/api/scrape?source_id=${scrapeBtn.dataset.id}`, { method: "POST" })
      .then((result) => toast(result.started
        ? "Scrape started — check logs in a minute"
        : "A scrape is already running"));
  }
});

document.addEventListener("change", (ev) => {
  if (ev.target.classList.contains("src-toggle")) {
    api(`/api/sources/${ev.target.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: ev.target.checked }),
    }).then(() => toast(ev.target.checked ? "Source enabled" : "Source disabled"));
  }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") $("#modal").hidden = true;
});

let searchTimer;
["f-search"].forEach((id) => {
  $("#" + id).addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadActivities, 250);
  });
});
["f-category", "f-status", "f-org", "f-free", "f-age", "f-sort"].forEach((id) => {
  $("#" + id).addEventListener("change", loadActivities);
});

$("#btn-scrape").addEventListener("click", () => {
  api("/api/scrape", { method: "POST" })
    .then((result) => toast(result.started
      ? "Full scrape started — sources appear in logs as they finish"
      : "A scrape is already running"));
});
$("#s-save").addEventListener("click", saveSettings);

/* boot */
(async function init() {
  await loadMeta();
  await loadActivities();
})();
