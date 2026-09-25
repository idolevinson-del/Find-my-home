const $ = (s, el = document) => el.querySelector(s);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};
const fmt = n => n == null ? "?" : Number(n).toLocaleString("he-IL");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let view = "inbox";
let settings = null;
let wasScanning = false;

// ---------- views ----------
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === b));
  view = b.dataset.view;
  $("#list").hidden = view === "settings";
  $("#hero").hidden = view === "settings";
  $("#settings").hidden = view !== "settings";
  view === "settings" ? renderSettings() : loadList();
}));

async function loadList() {
  const rows = await api(`/api/listings?view=${view}`);
  const list = $("#list");
  list.innerHTML = "";
  if (!rows.length) {
    const msg = { inbox: "עדיין אין דירות שמתאימות. הסוכן ממשיך לחפש 🔍", saved: "עוד לא שמרת דירות", rejected: "אין דירות שנדחו" }[view];
    list.innerHTML = `<div class="empty">${msg}</div>`;
    return;
  }
  rows.forEach(r => list.appendChild(card(r)));
}

function card(r) {
  const el = $("#card-tpl").content.firstElementChild.cloneNode(true);
  el.classList.toggle("is-new", !!r.is_new);
  const img = $(".gallery img", el);
  let i = 0;
  if (r.images.length) {
    img.addEventListener("error", () => { img.style.visibility = "hidden"; });
    img.addEventListener("load", () => { img.style.visibility = ""; });
    img.src = r.images[0];
    $(".img-count", el).textContent = r.images.length > 1 ? `1/${r.images.length}` : "";
    img.addEventListener("click", () => {
      i = (i + 1) % r.images.length;
      img.src = r.images[i];
      $(".img-count", el).textContent = `${i + 1}/${r.images.length}`;
    });
  } else img.remove();

  $(".place", el).textContent = r.neighborhood || r.street || r.title || "דירה";
  $(".street", el).textContent = [r.street, r.city].filter(Boolean).join(", ");
  const s = r.match_score ?? 0;
  $(".score-num", el).textContent = `${s}%`;
  $(".score", el).classList.add(s >= 85 ? "high" : s < 60 ? "low" : "mid");
  $(".price", el).textContent = r.price != null ? `₪${fmt(r.price)}` : "מחיר לא ידוע";
  $(".facts", el).textContent = [
    r.rooms != null ? `${r.rooms} חדרים` : null,
    r.size_sqm != null ? `${r.size_sqm} מ"ר` : null,
    r.floor != null ? (r.floor <= 0 ? "קרקע" : `קומה ${r.floor}`) : null,
    r.is_broker === true ? "תיווך" : r.is_broker === false ? "ללא תיווך" : null,
  ].filter(Boolean).join(" · ");
  const ul = $(".breakdown", el);
  (r.score_breakdown || []).forEach(b => {
    const li = document.createElement("li");
    li.className = b.state;
    li.textContent = b.label;
    ul.appendChild(li);
  });
  const ai = r.ai_analysis;
  if (ai) {
    const bits = [ai.summary && `🤖 ${esc(ai.summary)}`,
      ...(ai.red_flags || []).map(f => `⚠️ ${esc(f)}`)].filter(Boolean);
    $(".ai", el).innerHTML = bits.join("<br>");
  }
  if (r.description) $(".desc p", el).textContent = r.description; else $(".desc", el).remove();
  $(".open", el).href = r.url;

  const save = $(".save", el), reject = $(".reject", el);
  if (view === "saved") { save.textContent = "↩︎ הסר משמורות"; }
  if (view === "rejected") { reject.textContent = "↩︎ החזר"; save.remove(); }
  save.addEventListener("click", () => setStatus(r.id, view === "saved" ? "NEW" : "SAVED", el));
  reject.addEventListener("click", () => setStatus(r.id, view === "rejected" ? "NEW" : "REJECTED", el));
  return el;
}

async function setStatus(id, status, el) {
  await api(`/api/listings/${id}/status`, { method: "POST", body: JSON.stringify({ status }) });
  el.remove();
  if (!$("#list").children.length) loadList();
  refreshSummary();
}

// ---------- header / scan ----------
function searchChips(st) {
  const s = st.search, p = st.preferences;
  const rooms = s.min_rooms === s.max_rooms ? `${s.min_rooms} חדרים` : `${s.min_rooms || 0}–${s.max_rooms || "∞"} חדרים`;
  const chips = [s.city, rooms, `עד ₪${fmt(s.max_price)}`, s.min_size ? `${s.min_size}+ מ"ר` : null,
    (st.areas || []).map(a => a.name).join(" + ") || null,
    p.roommates ? `${p.roommates} שותפים` : null, s.exclude_ground_floor ? "בלי קרקע" : null].filter(Boolean);
  $("#search-summary").innerHTML = chips.map(c => `<span>${esc(c)}</span>`).join("");
}

async function refreshSummary() {
  const s = await api("/api/summary");
  const parts = [];
  if (s.excellent) parts.push(`${s.excellent} התאמות מצוינות`);
  if (s.good) parts.push(`${s.good} טובות`);
  if (s.possible) parts.push(`${s.possible} אפשריות`);
  $("#headline").innerHTML = s.new
    ? `🔥 ${s.new} דירות חדשות<small>${parts.join(" · ")}</small>`
    : s.total ? `${s.total} דירות מתאימות<small>${parts.join(" · ")}</small>` : "הסוכן מחפש לך דירה";
  const btn = $("#scan-btn");
  btn.disabled = s.scanning;
  btn.textContent = s.scanning ? "⏳ סורק…" : "🔍 סרוק עכשיו";
  const info = [];
  if (s.last_scan?.finished_at) info.push(`סריקה אחרונה: ${new Date(s.last_scan.finished_at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" })}`);
  if (s.last_scan?.error) info.push(`⚠️ יד2 לא זמין כרגע — ננסה שוב בסריקה הבאה`);
  if (s.next_scan_at && !s.scanning) info.push(`הבאה: ${new Date(s.next_scan_at * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" })}`);
  if (!s.telegram) info.push("טלגרם לא מחובר (ראה README)");
  $("#scan-info").textContent = info.join(" · ");
  if (wasScanning && !s.scanning && view !== "settings") loadList();
  wasScanning = s.scanning;
  return s;
}

$("#scan-btn").addEventListener("click", async () => {
  await api("/api/scan", { method: "POST" });
  wasScanning = true;
  $("#scan-btn").disabled = true;
  $("#scan-btn").textContent = "⏳ סורק…";
});

async function poll() {
  try { const s = await refreshSummary(); setTimeout(poll, s.scanning || wasScanning ? 3000 : 20000); }
  catch { setTimeout(poll, 20000); }
}

// ---------- settings ----------
function renderSettings() {
  const st = structuredClone(settings);
  const s = st.search, p = st.preferences, n = st.notifications;
  const num = (path, label, v, step = 1) => `<label>${label}<input type="number" step="${step}" data-path="${path}" value="${v ?? ""}"></label>`;
  const sel = (path, label, v, opts) => `<label>${label}<select data-path="${path}">${opts.map(([k, t]) => `<option value="${k}" ${k === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>`;
  const pref = [["preferred", "מועדף"], ["ignore", "לא משנה"]];
  $("#settings").innerHTML = `
  <form>
    <fieldset><legend>חיפוש</legend><div class="grid">
      <label>עיר<input data-path="search.city" value="${esc(s.city)}"></label>
      ${num("search.min_rooms", "מינימום חדרים", s.min_rooms, .5)}
      ${num("search.max_rooms", "מקסימום חדרים", s.max_rooms, .5)}
      ${num("search.max_price", "מחיר מקסימלי ₪", s.max_price, 100)}
      ${num("search.min_size", 'מינימום מ"ר', s.min_size)}
      ${sel("search.area_mode", "אזורים", s.area_mode, [["require", "רק באזורים שלי"], ["prefer", "העדף, אבל הראה הכל"]])}
      <label class="check"><input type="checkbox" data-path="search.exclude_ground_floor" ${s.exclude_ground_floor ? "checked" : ""}> בלי קומת קרקע</label>
    </div></fieldset>
    <fieldset><legend>אזורים ושכונות</legend><div id="areas"></div>
      <button type="button" class="link" id="add-group">+ קבוצת אזורים חדשה</button></fieldset>
    <fieldset><legend>העדפות</legend><div class="grid">
      ${num("preferences.roommates", "מספר שותפים", p.roommates)}
      ${sel("preferences.balcony", "מרפסת", p.balcony, pref)}
      ${sel("preferences.parking", "חניה", p.parking, pref)}
      ${sel("preferences.elevator", "מעלית", p.elevator, pref)}
      ${sel("preferences.broker", "תיווך", p.broker, [["allowed_not_preferred", "אפשרי, עדיף בלי"], ["ignore", "לא משנה"]])}
    </div></fieldset>
    <fieldset><legend>התראות וסריקה</legend><div class="grid">
      ${num("notifications.min_score", "ציון מינימלי להתראה", n.min_score)}
      ${num("notifications.max_per_scan", "מקסימום התראות לסריקה", n.max_per_scan)}
      ${num("schedule.scan_interval_minutes", "סריקה כל (דקות, מינ׳ 5)", st.schedule.scan_interval_minutes)}
      <label class="check"><input type="checkbox" data-path="notifications.telegram_enabled" ${n.telegram_enabled ? "checked" : ""}> התראות טלגרם</label>
      <label class="check"><input type="checkbox" data-path="ai.enabled" ${st.ai.enabled ? "checked" : ""}> ניתוח AI (Gemini)</label>
    </div></fieldset>
    <fieldset><legend>משקלות הציון</legend><div class="grid">
      ${Object.entries(st.scoring).map(([k, v]) => num(`scoring.${k}`, { price: "מחיר", area: "אזור", rooms: "חדרים", size: "גודל", floor: "קומה", balcony: "מרפסת", parking: "חניה", roommate_fit: "התאמה לשותפים", no_broker: "ללא תיווך", condition: "מצב הדירה", elevator: "מעלית" }[k] || k, v)).join("")}
    </div></fieldset>
    <div class="save-bar"><button class="primary" type="submit">שמור הגדרות</button><span class="toast"></span></div>
  </form>`;
  const areas = st.areas || [];
  const drawAreas = () => {
    $("#areas").innerHTML = "";
    areas.forEach((g, gi) => {
      const div = document.createElement("div");
      div.className = "area-group";
      div.innerHTML = `<div class="head"><input value="${esc(g.name)}"><button type="button" class="link">מחק קבוצה</button></div>
        <div class="chips">${(g.places || []).map((p, pi) => `<span class="chip">${esc(p)}<button type="button" data-pi="${pi}">✕</button></span>`).join("")}</div>
        <div class="add-row"><input placeholder="הוסף שכונה או רחוב (בעברית, כמו ביד2)"><button type="button">הוסף</button></div>`;
      $(".head input", div).addEventListener("input", e => g.name = e.target.value);
      $(".head button", div).addEventListener("click", () => { areas.splice(gi, 1); drawAreas(); });
      div.querySelectorAll(".chip button").forEach(b => b.addEventListener("click", () => { g.places.splice(+b.dataset.pi, 1); drawAreas(); }));
      const inp = $(".add-row input", div);
      const add = () => { const v = inp.value.trim(); if (v) { (g.places ||= []).push(v); drawAreas(); } };
      $(".add-row button", div).addEventListener("click", add);
      inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); add(); } });
      $("#areas").appendChild(div);
    });
  };
  drawAreas();
  $("#add-group").addEventListener("click", () => { areas.push({ name: "אזור חדש", places: [] }); drawAreas(); });

  $("#settings form").addEventListener("submit", async e => {
    e.preventDefault();
    const patch = { areas };
    e.target.querySelectorAll("[data-path]").forEach(inp => {
      const [sec, key] = inp.dataset.path.split(".");
      const val = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
      (patch[sec] ||= {})[key] = val;
    });
    settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) });
    searchChips(settings);
    $(".toast").textContent = "✓ נשמר — הציונים חושבו מחדש";
  });
}

// ---------- boot ----------
(async () => {
  settings = await api("/api/settings");
  searchChips(settings);
  await loadList();
  poll();
})();
