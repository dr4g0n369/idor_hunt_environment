const KNOWN_BUGS = [
  "idor_contractor_profile","idor_project_brief","idor_invoice",
  "idor_proposal","privesc_platform_config","privesc_all_earnings","privesc_flag_contractor"
];
const FALSE_POSITIVES = ["fp_skills","fp_browse_projects","fp_platform_stats"];

const BUG_LABELS = {
  idor_contractor_profile: "Contractor Profile IDOR",
  idor_project_brief:      "Project Brief IDOR",
  idor_invoice:            "Invoice IDOR",
  idor_proposal:           "Proposal IDOR",
  privesc_platform_config: "Platform Config Privesc",
  privesc_all_earnings:    "Earnings Dump Privesc",
  privesc_flag_contractor: "Flag Contractor Privesc",
};

let totalRequests = 0;
let bugsFound     = new Set();
let fpHit         = new Set();
let probedPaths   = new Set();
let connected     = false;

const termBody    = document.getElementById("terminal-body");
const statusPill  = document.getElementById("status-pill");
const statusText  = document.getElementById("status-text");
const reqCount    = document.getElementById("req-count");
const bugCount    = document.getElementById("bug-count");
const f1Score     = document.getElementById("f1-score");
const bugFraction = document.getElementById("bug-fraction");
const fpFraction  = document.getElementById("fp-fraction");

function addLine(text, cls = "") {
  const div = document.createElement("div");
  div.className = "term-line new" + (cls ? " " + cls : "");
  div.textContent = text;
  termBody.appendChild(div);
  termBody.scrollTop = termBody.scrollHeight;
  if (termBody.children.length > 300) termBody.removeChild(termBody.firstChild);
}

function methodColor(method) {
  return method === "GET" ? "\x1b[34m" : "\x1b[32m";
}

function statusClass(code) {
  if (code >= 200 && code < 300) return "ok";
  if (code === 401 || code === 403) return "warn";
  if (code === 404) return "dim";
  return "warn";
}

function markEndpointProbed(path) {
  const items = document.querySelectorAll(".endpoint-item");
  items.forEach(el => {
    const ep = el.dataset.path || "";
    const epNorm = ep.replace(/\{[^}]+\}/g, "\\d+");
    const re = new RegExp("^" + epNorm.replace(/[.*+?^${}()|[\]\\]/g, m => m === "\\d+" ? "\\d+" : "\\" + m) + "$");
    if (path === ep || re.test(path)) {
      if (!el.classList.contains("found")) el.classList.add("probed");
    }
  });
}

function markEndpointFound(bugId) {
  const el = document.querySelector(`.endpoint-item[data-bug="${bugId}"]`);
  if (el) {
    el.classList.remove("probed");
    el.classList.add("found");
  }
}

function updateScores() {
  const tp = bugsFound.size;
  const fp = fpHit.size;
  const fn = KNOWN_BUGS.length - tp;
  const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
  const recall    = KNOWN_BUGS.length > 0 ? tp / KNOWN_BUGS.length : 0;
  const f1        = precision + recall > 0 ? 2 * precision * recall / (precision + recall) : 0;

  const pct = v => Math.round(v * 100);

  document.getElementById("bar-precision").style.width = pct(precision) + "%";
  document.getElementById("bar-recall").style.width    = pct(recall)    + "%";
  document.getElementById("bar-f1").style.width        = pct(f1)        + "%";

  document.getElementById("val-precision").textContent = precision > 0 ? precision.toFixed(2) : "—";
  document.getElementById("val-recall").textContent    = recall > 0    ? recall.toFixed(2)    : "—";
  document.getElementById("val-f1").textContent        = f1 > 0        ? f1.toFixed(2)        : "—";

  bugCount.textContent = tp;
  f1Score.textContent  = f1 > 0 ? f1.toFixed(2) : "—";
  bugFraction.textContent = `${tp} / ${KNOWN_BUGS.length}`;
  fpFraction.textContent  = `${fpHit.size} / ${FALSE_POSITIVES.length}`;
}

function handleEvent(evt) {
  if (!evt.data) return;
  let msg;
  try { msg = JSON.parse(evt.data); } catch { return; }

  if (msg.type === "connected") {
    connected = true;
    statusPill.classList.add("active");
    statusText.textContent = "Agent Connected";
    addLine("─".repeat(52), "dim");
    addLine("▶ AI agent connected — audit session started", "info");
    addLine("─".repeat(52), "dim");
    return;
  }

  if (msg.type === "ping") return;

  if (msg.type === "request") {
    const d = msg.data;
    totalRequests++;
    reqCount.textContent = totalRequests;

    const sc = d.status;
    const cls = statusClass(sc);
    const ts  = new Date().toLocaleTimeString("en-GB", {hour12: false, hour:"2-digit", minute:"2-digit", second:"2-digit"});
    const line = `[${ts}]  ${d.method.padEnd(6)} ${d.path.padEnd(34)}  @${d.account.padEnd(8)}  HTTP ${sc}`;
    addLine(line, "req " + cls);

    markEndpointProbed(d.path);

    if (d.new_bugs && d.new_bugs.length > 0) {
      d.new_bugs.forEach(bid => {
        if (!bugsFound.has(bid)) {
          bugsFound.add(bid);
          addLine(`  ⚠  BUG FOUND: ${BUG_LABELS[bid] || bid}`, "bug");

          const biEl = document.getElementById(`bi-${bid}`);
          if (biEl) {
            biEl.classList.add("found");
            biEl.querySelector(".bi-icon").textContent = "●";
            biEl.style.animation = "none";
            void biEl.offsetHeight;
            biEl.style.animation = "";
          }
          markEndpointFound(bid);
        }
      });
    }

    if (d.new_fps && d.new_fps.length > 0) {
      d.new_fps.forEach(fid => {
        fpHit.add(fid);
        const fpiEl = document.getElementById(`fpi-${fid}`);
        if (fpiEl) {
          fpiEl.classList.add("hit");
          fpiEl.querySelector(".fpi-icon").textContent = "!";
        }
      });
    }

    updateScores();
  }
}

function connect() {
  const es = new EventSource("/api/audit/stream");
  es.onmessage = handleEvent;
  es.onerror = () => {
    if (connected) {
      statusPill.classList.remove("active");
      statusText.textContent = "Reconnecting…";
    }
    setTimeout(connect, 3000);
    es.close();
  };
}

async function loadInitialState() {
  try {
    const res  = await fetch("/api/audit/state");
    const data = await res.json();
    data.bugs_found.forEach(bid => {
      bugsFound.add(bid);
      const biEl = document.getElementById(`bi-${bid}`);
      if (biEl) { biEl.classList.add("found"); biEl.querySelector(".bi-icon").textContent = "●"; }
      markEndpointFound(bid);
    });
    data.fp_hit.forEach(fid => {
      fpHit.add(fid);
      const fpiEl = document.getElementById(`fpi-${fid}`);
      if (fpiEl) { fpiEl.classList.add("hit"); fpiEl.querySelector(".fpi-icon").textContent = "!"; }
    });
    totalRequests = data.total_requests;
    reqCount.textContent = totalRequests;
    updateScores();
  } catch {}
}

loadInitialState();
connect();
