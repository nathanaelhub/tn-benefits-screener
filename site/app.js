// The form builds a household in the screener's JSON format and runs the
// real Python engine (tn_screener.engine.screen) in Pyodide.

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const PROGRAMS = { snap: "Food assistance (SNAP)", wic: "WIC", tenncare: "TennCare / CoverKids" };
const STATUS = {
  likely: "Likely", possibly: "Possibly", unlikely: "Unlikely", refer: "Caseworker needs to look",
  already_enrolled: "Already enrolled", not_applicable: "Not applicable",
};

let screen = null;
const EMPTY_RESULTS = $("#results").innerHTML;

// Form --------------------------------------------------------------------

function addMember(m = {}) {
  const el = $("#member-tpl").content.firstElementChild.cloneNode(true);
  $(".age", el).value = m.age ?? "";
  $(".pregnant", el).checked = !!m.pregnant;
  $(".babies", el).value = m.babies_expected ?? 1;
  $(".postpartum", el).value = m.months_since_pregnancy_ended ?? "";
  $(".breastfeeding", el).checked = !!m.breastfeeding;
  $(".disabled", el).checked = !!m.disabled;
  $(".student", el).checked = !!m.college_student;
  $(".noncitizen", el).checked = m.us_citizen === false;
  $(".ssi", el).checked = !!m.gets_ssi;
  $(".ff", el).checked = !!m.gets_families_first;
  $(".remove", el).onclick = () => { el.remove(); renumber(); };
  $(".pregnant", el).onchange = () => syncMember(el);
  syncMember(el);
  $("#members").append(el);
  renumber();
}

function syncMember(el) {
  $(".babies-wrap", el).hidden = !$(".pregnant", el).checked;
}

function renumber() {
  $$("#members .member").forEach((el, i) => {
    $(".age", el).setAttribute("aria-label", `Person ${i + 1} age`);
    $(".remove", el).hidden = $$("#members .member").length === 1;
  });
}

function addIncome(inc = {}) {
  const el = $("#income-tpl").content.firstElementChild.cloneNode(true);
  $(".amount", el).value = inc.amount ?? "";
  $(".frequency", el).value = inc.frequency ?? "monthly";
  $(".kind", el).value = inc.kind ?? "earned";
  $(".remove", el).onclick = () => el.remove();
  $("#incomes").append(el);
}

const num = (id) => ($(id).value === "" ? null : Number($(id).value));

function household() {
  const members = $$("#members .member").map((el) => {
    const m = { age: Number($(".age", el).value) };
    if ($(".age", el).value === "") throw new Error("Enter an age for everyone in the household.");
    if ($(".pregnant", el).checked) { m.pregnant = true; m.babies_expected = Number($(".babies", el).value || 1); }
    if ($(".postpartum", el).value !== "") m.months_since_pregnancy_ended = Number($(".postpartum", el).value);
    if ($(".breastfeeding", el).checked) m.breastfeeding = true;
    if ($(".disabled", el).checked) m.disabled = true;
    if ($(".student", el).checked) m.college_student = true;
    if ($(".noncitizen", el).checked) m.us_citizen = false;
    if ($(".ssi", el).checked) m.gets_ssi = true;
    if ($(".ff", el).checked) m.gets_families_first = true;
    return m;
  });
  const income = $$("#incomes .income")
    .filter((el) => $(".amount", el).value !== "")
    .map((el) => ({ amount: Number($(".amount", el).value), frequency: $(".frequency", el).value, kind: $(".kind", el).value }));
  return {
    members, income,
    rent_or_mortgage: num("#rent"),
    utilities: $("#utilities").value || null,
    dependent_care: num("#care"),
    child_support_paid: num("#support") ?? 0,
    medical_costs: num("#medical"),
    resources: num("#savings"),
    homeless: $("#homeless").checked,
    receives: $$("input[name=receives]:checked").map((c) => c.value),
  };
}

function fill(h) {
  $("#members").replaceChildren();
  $("#incomes").replaceChildren();
  h.members.forEach(addMember);
  (h.income || []).forEach(addIncome);
  $("#rent").value = h.rent_or_mortgage ?? "";
  $("#utilities").value = h.utilities ?? "";
  $("#care").value = h.dependent_care ?? "";
  $("#support").value = h.child_support_paid || "";
  $("#medical").value = h.medical_costs ?? "";
  $("#savings").value = h.resources ?? "";
  $("#homeless").checked = !!h.homeless;
  $$("input[name=receives]").forEach((c) => { c.checked = (h.receives || []).includes(c.value); });
}

// Results -----------------------------------------------------------------

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const money = (x) => "$" + Number(x).toLocaleString("en-US", { maximumFractionDigits: 2 });

function cite(r, ids) {
  const seen = new Set();
  const items = ids.filter((id) => r.citations[id]).flatMap((id) => r.citations[id].sources).filter((s) => {
    if (seen.has(s.url)) return false;
    seen.add(s.url);
    return true;
  });
  if (!items.length) return "";
  return `<details class="sources"><summary>Sources (${items.length})</summary><ul>${items.map((s) =>
    `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.source)}</a>, ${esc(s.publisher)}${s.official ? "" : ' <span class="tag">unofficial</span>'}</li>`).join("")}</ul></details>`;
}

function render(r) {
  const cards = Object.entries(PROGRAMS).map(([key, title]) => {
    const p = r.programs[key];
    const est = p.estimate ? `<p class="estimate">About <strong>${money(p.estimate.monthly_benefit)}</strong> a month <span>(estimate)</span></p>` : "";
    const people = p.people ? `<ul class="people">${p.people.map((x) =>
      `<li><span class="badge s-${x.status}">${STATUS[x.status]}</span> <strong>${esc(x.name)}</strong> · ${esc(x.program)}<br><span class="muted">${esc(x.reason)}</span></li>`).join("")}</ul>` : "";
    const reasons = p.reasons.length ? `<details><summary>How this was worked out</summary><ol>${p.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ol></details>` : "";
    const notes = p.notes.map((n) => `<p class="note">${esc(n)}</p>`).join("");
    return `<article class="card program">
      <header><h3>${title}</h3><span class="badge s-${p.status}">${STATUS[p.status]}</span></header>
      <p>${esc(p.summary)}</p>${est}${people}${notes}${reasons}${cite(r, p.rules)}</article>`;
  }).join("");
  const missing = r.missing_facts.length ? `<div class="card ask"><h3>Questions that could change this</h3><ul>${r.missing_facts.map((m) =>
    `<li><strong>${esc(m.ask)}</strong><br><span class="muted">${esc(m.why)}</span></li>`).join("")}</ul></div>` : "";
  const steps = `<div class="card steps"><h3>Next steps</h3><ul>${r.next_steps.map((s) =>
    `<li>${esc(s.how)}${s.url ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">apply online</a>` : ""}</li>`).join("")}</ul></div>`;
  const warn = r.warnings.map((w) => `<p class="note">${esc(w)}</p>`).join("");
  $("#results").innerHTML = `<h2 class="sr-only">Results</h2>${missing}${cards}${steps}
    <p class="disclaimer">${esc(r.disclaimer)} Rules in force on ${esc(r.as_of)}.</p>${warn}`;
  $("#results").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}

// Wiring ------------------------------------------------------------------

$("#add-member").onclick = () => addMember();
$("#add-income").onclick = () => addIncome();
$("#form").onsubmit = (e) => {
  e.preventDefault();
  const err = $("#form-error");
  err.hidden = true;
  try {
    render(screen(household()));
  } catch (ex) {
    // Don't leave the previous household's results next to the error.
    $("#results").innerHTML = EMPTY_RESULTS;
    err.textContent = String(ex.message || ex).split("\n").filter(Boolean).pop();
    err.hidden = false;
  }
};

addMember();
addIncome();

fetch("examples.json").then((r) => r.json()).then((list) => {
  $("#examples").replaceChildren(...list.map((ex) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = ex.name;
    b.onclick = () => { fill(ex.household); if (screen) $("#form").requestSubmit(); };
    return b;
  }));
});

(async () => {
  const go = $("#go");
  try {
    const py = await loadPyodide();
    py.unpackArchive(await (await fetch("screener.zip")).arrayBuffer(), "zip");
    py.runPython("import json\nfrom tn_screener.engine import screen as _screen");
    screen = (h) => {
      py.globals.set("household_json", JSON.stringify(h));
      return JSON.parse(py.runPython("json.dumps(_screen(json.loads(household_json)))"));
    };
    window.tnScreen = screen; // for automated tests
    go.disabled = false;
    go.textContent = "Check eligibility";
  } catch (ex) {
    go.textContent = "The screener couldn't load";
    $("#form-error").textContent = "Couldn't load the screener: " + ex;
    $("#form-error").hidden = false;
  }
})();
