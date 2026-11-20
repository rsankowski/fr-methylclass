"use strict";

const $ = (id) => document.getElementById(id);
const paths = [];            // selected input paths
let current = null;          // run being shown
let logOffset = 0;
let pollTimer = null;
let logRest = "";           // partial last line of the log

const TOOL_LABELS = {
  crossnn: "crossNN", methylyzr: "MethyLYZR", sturgeon: "Sturgeon V2", lamprey: "Lamprey",
  rapidcns2: "rapidCNS2", cnv: "Copy-number", metagenomics: "Metagenomics", report: "PDF report",
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

// --------------------------------------------------------------------------
// Settings (references + models on the main page, the rest in the modal)
// --------------------------------------------------------------------------
function readSettings() {
  const s = {};
  document.querySelectorAll(".setting").forEach((el) => {
    s[el.id] = el.type === "checkbox" ? el.checked : el.value.trim();
  });
  return s;
}

function fillSettings(s) {
  document.querySelectorAll(".setting").forEach((el) => {
    if (!(el.id in s)) return;
    if (el.type === "checkbox") el.checked = !!s[el.id];
    else el.value = s[el.id] ?? "";
  });
}

async function saveSettings() {
  return (await api("/api/settings", readSettings())).settings;
}

async function loadSettings() {
  const d = await api("/api/settings");
  fillSettings(d.settings);
  $("repoInfo").innerHTML = `Pipeline: <code>${esc(d.repo)}</code> · Nextflow: <code>${esc(d.nextflow)}</code>` +
    ` · settings are stored in <code>gui/settings.json</code>`;
}

$("settingsBtn").onclick = () => $("settings").classList.remove("hidden");
$("settingsClose").onclick = () => $("settings").classList.add("hidden");
$("settingsSave").onclick = async () => {
  try { await saveSettings(); $("settingsMsg").textContent = "Saved."; await loadSettings(); }
  catch (e) { $("settingsMsg").textContent = "Error: " + e.message; }
  setTimeout(() => ($("settingsMsg").textContent = ""), 2500);
};
document.querySelectorAll("#hg19_fasta,#hg38_fasta,#chm13_fasta,#assets_dir")
  .forEach((el) => el.addEventListener("change", () => saveSettings().catch(() => {})));

// --------------------------------------------------------------------------
// Input path management
// --------------------------------------------------------------------------
function renderPaths() {
  const ul = $("pathList");
  ul.innerHTML = "";
  paths.forEach((p, i) => {
    const li = document.createElement("li");
    li.textContent = p;
    const x = document.createElement("span");
    x.className = "remove";
    x.textContent = "✕";
    x.title = "Remove";
    x.onclick = () => { paths.splice(i, 1); renderPaths(); discover(); };
    li.appendChild(x);
    ul.appendChild(li);
  });
  if (!paths.length) $("discoverSummary").classList.add("hidden");
}

function addPath(p) {
  p = (p || "").trim();
  if (!p || paths.includes(p)) return;
  paths.push(p);
  renderPaths();
  discover();
}

$("addPathBtn").onclick = () => { addPath($("pathInput").value); $("pathInput").value = ""; };
$("pathInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { addPath($("pathInput").value); $("pathInput").value = ""; }
});

function groupMode() {
  const el = document.querySelector('input[name="groupMode"]:checked');
  return el ? el.value : "folder";
}

async function discover() {
  if (!paths.length) return;
  const sum = $("discoverSummary");
  sum.classList.remove("hidden");
  sum.textContent = "Scanning…";
  try {
    const d = await api("/api/discover", { paths, group_by: groupMode() });
    const bad = !d.samples.length;
    sum.style.background = bad ? "#fdecea" : "#eef7f0";
    sum.style.borderColor = bad ? "#f5c6cb" : "#bfe3c9";
    sum.style.color = bad ? "#a23a30" : "#245d36";
    const warn = d.warnings.map((w) => `<li>⚠ ${esc(w)}</li>`).join("");
    if (bad) {
      sum.innerHTML = "No .bam files found in the selected inputs." + (warn ? `<ul class="sample-list">${warn}</ul>` : "");
    } else {
      const rows = d.samples.map((s) =>
        `<li><strong>${esc(s.sample)}</strong> — ${s.n_bams} BAM${s.n_bams > 1 ? "s" : ""} · ${s.size_gb} GB</li>`).join("");
      sum.innerHTML = `<strong>${d.samples.length} sample(s)</strong> from ${d.n_bams} BAM file(s) · ` +
        `${d.size_gb} GB total<ul class="sample-list">${rows}${warn}</ul>`;
    }
  } catch (e) {
    sum.textContent = "Error scanning inputs: " + e.message;
  }
}
document.querySelectorAll('input[name="groupMode"]').forEach((el) => el.addEventListener("change", discover));

// --------------------------------------------------------------------------
// Filesystem browser modal
// --------------------------------------------------------------------------
let browseTarget = null;     // "input" or the id of a text field
let browseMode = "bam";
let browseCurrent = "";

async function openBrowser(target, mode) {
  browseTarget = target;
  browseMode = mode;
  $("browser").classList.remove("hidden");
  $("browserSelectDir").classList.toggle("hidden", !(target === "input" || mode === "dir"));
  let start = "";
  if (target !== "input" && $(target).value.trim()) start = $(target).value.trim();
  else if (target === "input" && paths.length) start = paths[paths.length - 1];
  await loadDir(start);
}

async function loadDir(path) {
  let d;
  try { d = await api(`/api/browse?mode=${browseMode}&path=` + encodeURIComponent(path)); }
  catch (e) { alert(e.message); return; }
  browseCurrent = d.path;
  $("browserPath").textContent = d.path;
  $("browserHome").onclick = () => loadDir(d.home);
  const ul = $("browserList");
  ul.innerHTML = "";
  if (d.parent !== null) ul.appendChild(makeRow("⬆", "..", () => loadDir(d.parent), true));
  d.entries.forEach((e) => {
    if (e.dir) ul.appendChild(makeRow("📁", e.name, () => loadDir(e.path), true));
    else ul.appendChild(makeRow(browseMode === "bam" ? "🧬" : "📄", e.name, () => pick(e.path), false));
  });
}

function pick(p) {
  if (browseTarget === "input") addPath(p);
  else { $(browseTarget).value = p; $(browseTarget).dispatchEvent(new Event("change")); }
  closeBrowser();
}

function makeRow(icon, label, onclick, isDir) {
  const li = document.createElement("li");
  if (isDir) li.className = "dir";
  li.innerHTML = `<span class="ic">${icon}</span><span>${esc(label)}</span>`;
  li.onclick = onclick;
  return li;
}

function closeBrowser() { $("browser").classList.add("hidden"); }
$("browseBtn").onclick = () => openBrowser("input", "bam");
document.querySelectorAll(".browseField").forEach((b) => {
  b.onclick = () => openBrowser(b.dataset.target, b.dataset.mode);
});
$("browserClose").onclick = closeBrowser;
$("browserSelectDir").onclick = () => pick(browseCurrent);
$("browser").addEventListener("click", (e) => { if (e.target.id === "browser") closeBrowser(); });
$("settings").addEventListener("click", (e) => { if (e.target.id === "settings") $("settings").classList.add("hidden"); });

// --------------------------------------------------------------------------
// Run form
// --------------------------------------------------------------------------
function selectedTools() {
  return [...document.querySelectorAll(".tool input:checked")].map((c) => c.value);
}

function formData(extra = {}) {
  return Object.assign({
    paths, group_by: groupMode(), tools: selectedTools(),
    outdir: $("outInput").value.trim(), patient_id: $("patientId").value.trim(),
    resume: $("optResume").checked, cleanup: $("optCleanup").checked, stub: $("optStub").checked,
    extra_params: $("extraParams").value,
  }, extra);
}

function hint(msg) { $("runHint").textContent = msg; }

$("runBtn").onclick = () => launch(formData());
$("testBtn").onclick = () => launch({ test: true, resume: false, tools: [] });

async function launch(form) {
  if (!form.test) {
    if (!paths.length) return hint("Add at least one input path first.");
    if (!form.tools.length) return hint("Select at least one classifier.");
  }
  hint("Starting…");
  $("runBtn").disabled = true;
  try {
    await saveSettings();
    const run = await api("/api/run", form);
    hint("");
    show(run);
    refreshRuns();
  } catch (e) {
    hint(e.message);
  } finally {
    $("runBtn").disabled = false;
  }
}

$("checkBtn").onclick = async () => {
  $("checkCard").classList.remove("hidden");
  $("checkList").innerHTML = "<li>Checking… (the first Nextflow call can take a minute)</li>";
  try {
    await saveSettings();
    const d = await api("/api/check", formData());
    const icon = { ok: "✔", warn: "⚠", error: "✖" };
    $("checkList").innerHTML = d.checks.map((c) =>
      `<li><span class="${c.status}">${icon[c.status]}</span><span>${esc(c.name)}</span>` +
      `<span class="d">${esc(c.detail)}</span></li>`).join("");
    const nErr = d.checks.filter((c) => c.status === "error").length;
    hint(nErr ? `${nErr} problem(s) found, see Setup check.` : "Setup looks good.");
  } catch (e) {
    $("checkList").innerHTML = `<li>Error: ${esc(e.message)}</li>`;
  }
};

$("previewBtn").onclick = async () => {
  try {
    await saveSettings();
    const d = await api("/api/preview", formData());
    $("previewCard").classList.remove("hidden");
    $("previewCmd").textContent = d.command;
    $("previewParams").textContent = JSON.stringify(d.params, null, 2) +
      (d.errors.length ? "\n\n# problems:\n# " + d.errors.join("\n# ") : "");
  } catch (e) { hint(e.message); }
};

$("quitBtn").onclick = async () => {
  const live = (await api("/api/runs")).filter((r) => r.status === "running").length;
  const msg = "Stop the GUI?" + (live ? `\n\n${live} run(s) keep running in the background; ` +
    "open the GUI again to follow them." : "");
  if (!confirm(msg)) return;
  await api("/api/quit", {}).catch(() => {});
  document.body.innerHTML = "<main><section class='card'><h2>GUI stopped</h2>" +
    "<p>You can close this tab. Double-click the fr-methylclass icon to start it again.</p></section></main>";
};

// --------------------------------------------------------------------------
// Run monitor
// --------------------------------------------------------------------------
function setStatus(status) {
  const pill = $("jobStatus");
  pill.textContent = status;
  pill.className = "status-pill " + status;
}

function show(run) {
  const switching = !current || current.id !== run.id;
  current = run;
  if (switching) { logOffset = 0; logRest = ""; $("logView").textContent = ""; $("results").innerHTML = ""; }
  $("jobCard").classList.remove("hidden");
  $("jobPath").textContent = run.outdir;
  setStatus(run.status);
  if (switching) $("jobCard").scrollIntoView({ behavior: "smooth" });
  clearTimeout(pollTimer);
  poll();
}

async function poll() {
  if (!current) return;
  const id = current.id;
  try {
    const [run, log] = await Promise.all([
      api("/api/run/" + id), api(`/api/log/${id}?offset=${logOffset}`)]);
    if (!current || current.id !== id) return;
    current = run;
    setStatus(run.status);
    $("cancelBtn").classList.toggle("hidden", run.status !== "running");
    appendLog(log.text, log.truncated);
    logOffset = log.offset;
    renderTasks(run);
    renderResults(run);
    if (run.status === "running") pollTimer = setTimeout(poll, 2500);
    else refreshRuns();
  } catch (e) {
    pollTimer = setTimeout(poll, 5000);
  }
}

function appendLog(text, truncated) {
  if (!text) return;
  const view = $("logView");
  const atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
  if (truncated && !view.textContent) {
    const s = document.createElement("span");
    s.className = "step";
    s.textContent = "… (earlier output in fr-methylclass-gui.log)\n";
    view.appendChild(s);
  }
  const lines = (logRest + text).split("\n");
  logRest = lines.pop();     // wait for the rest of an unfinished line
  const frag = document.createDocumentFragment();
  for (const line of lines) {
    const span = document.createElement("span");
    if (line.startsWith("[gui]")) span.className = "cmd";
    else if (/ERROR|error|fail|WARN/i.test(line) && !/Submitted process/.test(line)) span.className = "err";
    span.textContent = line + "\n";
    frag.appendChild(span);
  }
  view.appendChild(frag);
  if (view.childNodes.length > 6000) {
    while (view.childNodes.length > 5000) view.removeChild(view.firstChild);
  }
  if (atBottom) view.scrollTop = view.scrollHeight;
}

function renderTasks(run) {
  const counts = run.counts || {};
  const parts = Object.entries(counts).map(([k, v]) => `${k.toLowerCase()}: <b>${v}</b>`);
  $("counts").innerHTML = parts.length ? "Tasks — " + parts.join(" · ") : "";
  const grid = $("stepGrid");
  grid.innerHTML = (run.tasks || []).map((t) => {
    const st = (t.status || "?").toLowerCase();
    const label = st === "running" ? "running" : st;
    return `<div class="step" title="${esc(t.hash)}${t.duration ? " · " + esc(t.duration) : ""}">` +
      `<span>${esc(t.name)}</span><span class="badge ${esc(st)}">${esc(label)}</span></div>`;
  }).join("");
}

function renderResults(run) {
  const groups = run.results || [];
  if (!groups.length) { $("results").innerHTML = ""; return; }
  const link = (rel) => `/api/file/${run.id}?rel=${encodeURIComponent(rel)}`;
  $("results").innerHTML = "<h3 class='log-title' style='margin-top:6px'>Results</h3>" + groups.map((g) =>
    `<h4>${esc(g.title)}</h4><ul>` + g.files.map((f) =>
      `<li><a href="${link(f)}" target="_blank" rel="noopener">${esc(f.split("/").pop())}</a></li>`).join("") +
    "</ul>").join("");
}

$("cancelBtn").onclick = async () => {
  if (!current || !confirm("Cancel this run? Nextflow stops its running tasks.")) return;
  $("cancelBtn").disabled = true;
  try { await api("/api/cancel/" + current.id, {}); } catch (e) { hint(e.message); }
  setTimeout(() => ($("cancelBtn").disabled = false), 3000);
};
$("openBtn").onclick = () => current && api("/api/open/" + current.id, {}).catch((e) => hint(e.message));

// --------------------------------------------------------------------------
// Previous runs
// --------------------------------------------------------------------------
async function refreshRuns() {
  let runs = [];
  try { runs = await api("/api/runs"); } catch (e) { return; }
  const ul = $("runList");
  ul.innerHTML = runs.length ? "" : "<li style='cursor:default'>No runs yet.</li>";
  runs.slice(0, 30).forEach((r) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="status-pill ${esc(r.status)}">${esc(r.status)}</span>` +
      `<span class="lbl">${esc(r.label)}</span><span class="when">${esc(r.started.replace("T", " "))}</span>` +
      `<span class="remove" title="Remove from this list (files are kept)">✕</span>`;
    li.onclick = (e) => {
      if (e.target.classList.contains("remove")) {
        e.stopPropagation();
        api("/api/forget/" + r.id, {}).then(refreshRuns);
        return;
      }
      show(r);
    };
    ul.appendChild(li);
  });
  return runs;
}

// --------------------------------------------------------------------------
// start-up
// --------------------------------------------------------------------------
(async () => {
  try { await loadSettings(); } catch (e) { hint("Could not load settings: " + e.message); }
  const runs = await refreshRuns();
  const live = (runs || []).find((r) => r.status === "running");
  if (live) show(live);
})();
