// Procurement Request Copilot UI. Vanilla JS, no build step.
// Security: every piece of business data is inserted with textContent, never parsed as HTML.
"use strict";

const LABELS = {
  route_for_approval: "Route for approval",
  route_for_specialist_review: "Route for specialist review",
  request_clarification: "Request clarification",
  use_existing_tool: "Use existing tool",
};
const ACTIONS = [
  ["send_for_approvals", "Send for approvals"],
  ["request_clarification", "Request clarification"],
  ["suggest_existing_tool", "Suggest existing tool"],
  ["hold_manual_review", "Hold for manual review"],
];
const FLAG_HELP = {
  existing_tool_overlap: "A catalog product shares this category or product name. Check whether it already covers the need.",
  budget_insufficient: "The annual cost exceeds the department's available software budget. Finance must review an exception.",
  budget_unverified: "No budget record exists for this department, so the budget could not be checked.",
  security_review_required: "Security must review before any business approval.",
  privacy_review_required: "Privacy must review (personal data or possible out-of-region storage).",
  legal_review_required: "Legal must review (new vendor at $10,000 or more, non-standard terms, or a cross-region issue).",
  vendor_review_expired: "The vendor's security review is older than 365 days or reported expired.",
  conflicting_vendor_evidence: "The internal registry and the vendor-risk service disagree. Neither is trusted on its own.",
  vendor_risk_unavailable: "The vendor-risk service could not be reached. Its status was not assumed.",
  vendor_not_registered: "The vendor is not in the internal registry. Treated as new, with unknown terms.",
  prompt_injection_detected: "Text in the business data tried to give instructions. It was ignored.",
  missing_information: "Required request fields are missing. The request goes back to the requester.",
  unrecognized_data_access_level: "The declared data-access level is not recognised, so sensitive data cannot be ruled out.",
  llm_unavailable: "AI analysis was unavailable. This result comes from the deterministic rules only.",
};
const RULE_SOURCES = new Set(["evaluate_policy_rules", "injection_scan"]);

const state = { selected: null, analysis: null, pendingAction: null, requests: [] };
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") node.textContent = v == null ? "" : String(v);
    else if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function money(v) {
  return typeof v === "number" ? "$" + v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "missing";
}

// ---------------------------------------------------------------- health + queue
async function loadHealth() {
  try {
    const h = await api("/api/health");
    $("dot-vendor").className = "dot " + (h.vendor_api === "ok" ? "ok" : "down");
    $("health-vendor").textContent = "Vendor API " + h.vendor_api;
    $("dot-llm").className = "dot " + (h.llm.configured ? "ok" : "down");
    $("health-llm").textContent = `${h.llm.provider} · ${h.llm.model}` + (h.llm.configured ? "" : " (not configured)");
  } catch (e) {
    $("health-vendor").textContent = "Health check failed";
  }
}

async function loadQueue() {
  const stateBox = $("queue-state");
  stateBox.hidden = false;
  clear(stateBox);
  stateBox.className = "muted";
  stateBox.textContent = "Loading requests…";
  try {
    state.requests = await api("/api/requests");
  } catch (e) {
    stateBox.className = "error";
    stateBox.textContent = "Could not load the queue: " + e.message + " ";
    stateBox.appendChild(el("button", { class: "secondary", text: "Retry", onclick: loadQueue }));
    return;
  }
  const list = $("queue");
  clear(list);
  if (!state.requests.length) {
    stateBox.textContent = "No purchase requests awaiting review";
    return;
  }
  stateBox.hidden = true;
  for (const r of state.requests) {
    const item = el("li", { class: "queue-item" + (r.request_id === state.selected ? " active" : ""), tabindex: "0" }, [
      el("div", { class: "q-top" }, [
        el("span", { class: "q-id", text: r.request_id }),
        el("span", { class: "status " + r.status.toLowerCase().replace(/\s+/g, "-"), text: r.status }),
      ]),
      el("div", { class: "q-product", text: `${r.product_name || "— missing"} · ${r.vendor_name || "— missing"}` }),
      el("div", { class: "q-meta muted", text: `${r.requester || "unknown"} · ${r.department || "unknown dept"} · ${money(r.annual_cost)} · ${r.urgency || "—"}` }),
    ]);
    item.addEventListener("click", () => selectRequest(r.request_id));
    item.addEventListener("keydown", (ev) => { if (ev.key === "Enter") selectRequest(r.request_id); });
    list.appendChild(item);
  }
}

// ---------------------------------------------------------------- request card
async function selectRequest(id) {
  state.selected = id;
  state.analysis = null;
  $("detail-empty").hidden = true;
  $("detail-body").hidden = false;
  $("result").hidden = true;
  $("result-error").hidden = true;
  $("run-state").textContent = "";
  for (const li of document.querySelectorAll(".queue-item")) {
    li.classList.toggle("active", li.querySelector(".q-id").textContent === id);
  }
  try {
    const data = await api("/api/requests/" + encodeURIComponent(id));
    renderRequest(data.request, data.requester);
  } catch (e) {
    $("req-title").textContent = "Could not load " + id + ": " + e.message;
  }
}

function renderRequest(r, requester) {
  $("req-title").textContent = `${r.request_id}: ${r.product_name || "— missing"}`;
  const dl = $("req-fields");
  clear(dl);
  const show = (v) => (v === null || v === undefined || v === "" ? "— missing" : v);
  const ints = Array.isArray(r.requested_integrations)
    ? (r.requested_integrations.length ? r.requested_integrations.join(", ") : "none")
    : "— missing";
  const rows = [
    ["Vendor", show(r.vendor_name)],
    ["Category", show(r.category)],
    ["Requester", requester && requester.known ? `${requester.name} (${r.requester_id})` : `${show(r.requester_id)} (unknown employee)`],
    ["Department", requester && requester.department ? requester.department : "— missing"],
    ["Annual cost", money(r.annual_cost_usd)],
    ["Users / licences", show(r.user_count)],
    ["Data access level", show(r.data_access_level)],
    ["Integrations", ints],
    ["Urgency", show(r.urgency)],
  ];
  for (const [k, v] of rows) {
    dl.appendChild(el("dt", { text: k }));
    dl.appendChild(el("dd", { text: v }));
  }
  $("req-justification").textContent = r.business_justification || "— missing";
}

// ---------------------------------------------------------------- analysis
async function analyze() {
  if (!state.selected) return;
  const rid = state.selected; // the request this analysis belongs to
  const arch = document.querySelector('input[name="arch"]:checked').value;
  $("btn-analyze").disabled = true;
  $("result").hidden = true;
  $("result-error").hidden = true;
  $("run-state").textContent = "Gathering evidence: budget · catalog · vendor · policy…";
  try {
    const result = await api("/api/analyze", { method: "POST", body: JSON.stringify({ request_id: rid, architecture: arch }) });
    if (state.selected !== rid) return; // the reviewer moved to another request; drop the late result
    state.analysis = { ...result, request_id: rid };
    renderAnalysis(state.analysis);
    $("run-state").textContent = "";
    loadQueue();
  } catch (e) {
    if (state.selected !== rid) return;
    $("run-state").textContent = "";
    $("result-error-text").textContent = "Analysis failed: " + e.message;
    $("result-error").hidden = false;
  } finally {
    $("btn-analyze").disabled = false;
  }
}

function renderAnalysis(a) {
  const d = a.decision;
  $("result").hidden = false;

  // banners
  const banners = $("banners");
  clear(banners);
  for (const b of a.banners) {
    const box = el("div", { class: "banner " + b.kind }, [el("strong", { text: b.text })]);
    if (b.compare) {
      const t = el("table", { class: "table compare" }, [
        el("thead", {}, el("tr", {}, [el("th", { text: "Source" }), el("th", { text: "Security status" }), el("th", { text: "Review date" })])),
      ]);
      const tb = el("tbody");
      for (const c of b.compare) tb.appendChild(el("tr", {}, [el("td", { text: c.source }), el("td", { text: c.status || "—" }), el("td", { text: c.review_date || "none" })]));
      t.appendChild(tb);
      box.appendChild(t);
    }
    if (b.quotes) {
      for (const q of b.quotes) {
        box.appendChild(el("div", { class: "quote-label small", text: "Quoted from " + q.field + " (data, not instructions):" }));
        box.appendChild(el("blockquote", { class: "quoted", text: q.excerpt }));
      }
    }
    banners.appendChild(box);
  }

  // recommendation
  const [label, ...rest] = d.recommendation.split(":");
  $("rec-badge").textContent = label;
  $("rec-badge").className = "badge " + a.decision_type;
  $("rec-text").textContent = rest.join(":").trim();
  $("next-text").textContent = d.next_step;

  // approvals with reasons
  const approvals = $("approvals");
  clear(approvals);
  const hints = { Manager: a.policy.requester && a.policy.requester.manager_hint, "Department Head": a.policy.requester && a.policy.requester.department_head_hint };
  for (const role of d.required_approvals) {
    const reasons = a.policy.approval_reasons[role] || [];
    const det = el("details", { class: "chip-detail" }, [
      el("summary", { class: "chip", text: role }),
      el("ul", { class: "plain small" }, reasons.map((r) => el("li", { text: `${r.rule} (${r.policy_ref}): ${r.detail}` }))),
    ]);
    if (hints[role]) det.appendChild(el("div", { class: "small muted", text: "Name hint: " + hints[role] }));
    approvals.appendChild(el("li", {}, det));
  }

  // flags
  const flags = $("flags");
  clear(flags);
  if (!d.risk_flags.length) flags.appendChild(el("li", { class: "muted", text: "No risk flags." }));
  for (const f of d.risk_flags) {
    flags.appendChild(el("li", {}, [el("span", { class: "chip flag", text: f }), el("span", { class: "small", text: " " + (FLAG_HELP[f] || "") })]));
  }

  // missing + questions
  fillList($("missing"), d.missing_information, "Nothing missing.");
  fillList($("questions"), a.questions_for_reviewer, "None.");

  // evidence
  const ev = $("evidence");
  clear(ev);
  d.evidence.forEach((e, i) => {
    const kind = i < a.deterministic_evidence ? (RULE_SOURCES.has(e.source) ? "Rule" : "Tool") : "AI analysis";
    ev.appendChild(el("tr", {}, [el("td", { text: e.source }), el("td", { text: e.finding }), el("td", { text: e.reference || "—" }), el("td", { text: kind })]));
  });

  // how this was decided
  const m = a.trace_meta;
  $("how-meta").textContent = `stop_reason: ${m.stop_reason} · final_mode: ${m.final_mode}` + (m.error ? ` · ${m.error}` : "");
  const steps = $("steps");
  clear(steps);
  for (const s of a.trace_steps) {
    steps.appendChild(el("tr", {}, [
      el("td", { text: s.n }), el("td", { text: s.actor }), el("td", { text: s.action }), el("td", { text: s.summary_out }),
      el("td", { text: s.route_reason || (s.ms != null ? Math.round(s.ms) + " ms" : "") }),
    ]));
  }
  const counts = m.event_counts || {};
  const corrections = ["code_restored_approval", "code_restored_flag", "llm_role_dropped", "llm_flag_dropped", "llm_added_review",
    "llm_decision_overridden", "ungrounded_evidence_removed", "output_guardrail_triggered", "tool_rejected", "repeated_tool_call"]
    .filter((k) => counts[k]).map((k) => `${k}: ${counts[k]}`);
  const gate = Object.keys(counts).filter((k) => k.startsWith("gate_filled:")).map((k) => k.replace("gate_filled:", ""));
  if (gate.length) corrections.push("gate filled: " + gate.join(", "));
  fillList($("corrections"), corrections, "None.");
  const audit = m.analyst_audit;
  $("audit-box").hidden = !audit;
  if (audit) {
    fillList($("analyst-audit"), [
      "Issues found: " + (audit.issues_found.length ? audit.issues_found.join("; ") : "none"),
      "Rejected claims: " + (audit.rejected_claims.length ? audit.rejected_claims.join("; ") : "none"),
      "Agrees with the analyst's overlap assessment: " + (audit.agrees_with_overlap_assessment ? "yes" : "no"),
    ], "");
  }

  // footer
  $("footer-line").textContent = `${m.architecture} · ${m.provider} ${m.model} · LLM calls ${m.llm_calls} · tool calls ${m.tool_calls} · ` +
    `active ${Math.round(m.latency_active_ms)} ms · run ${m.run_id} · This copilot cannot approve, purchase or notify anyone.`;

  renderActions(a);
  loadAudit();
}

function fillList(node, items, emptyText) {
  clear(node);
  if (!items || !items.length) {
    if (emptyText) node.appendChild(el("li", { class: "muted", text: emptyText }));
    return;
  }
  for (const it of items) node.appendChild(el("li", { text: it }));
}

// ---------------------------------------------------------------- actions + confirmation
function renderActions(a) {
  const box = $("action-buttons");
  clear(box);
  $("action-success").hidden = true;
  for (const [key, label] of ACTIONS) {
    const recommended = key === a.recommended_action;
    box.appendChild(el("button", {
      class: recommended ? "primary" : "secondary",
      text: label + (recommended ? " (recommended)" : ""),
      onclick: () => openConfirm(key, label),
    }));
  }
}

async function openConfirm(action, label) {
  const a = state.analysis;
  state.pendingAction = action;
  $("confirm-title").textContent = label;
  $("confirm-error").hidden = true;
  $("confirm-reason").value = "";
  $("confirm-override").hidden = true;
  $("reason-hint").textContent = "";
  $("confirm-ok").disabled = true; // enabled only once the consequence is shown (AC-5.2)
  $("confirm-consequence").textContent = "Loading the consequence…";
  try {
    const c = await api(`/api/consequence?run_id=${encodeURIComponent(a.trace_meta.run_id)}&action=${encodeURIComponent(action)}`);
    $("confirm-consequence").textContent = c.text;
    $("confirm-override").hidden = !c.override;
    $("reason-hint").textContent = c.override ? "(required)" : "(optional)";
    $("confirm-ok").disabled = false;
  } catch (e) {
    $("confirm-consequence").textContent = "Could not load the consequence: " + e.message + ". Close and try again.";
  }
  $("confirm").showModal();
}

async function confirmAction() {
  const a = state.analysis;
  const reason = $("confirm-reason").value.trim();
  if (!$("confirm-override").hidden && !reason) {
    $("confirm-error").textContent = "Please give a reason for overriding the recommendation.";
    $("confirm-error").hidden = false;
    return;
  }
  try {
    const entry = await api("/api/actions", { method: "POST", body: JSON.stringify({
      request_id: a.request_id, run_id: a.trace_meta.run_id, action: state.pendingAction, reason: reason || null,
    }) });
    $("confirm").close();
    const when = new Date(entry.timestamp).toLocaleTimeString();
    $("action-success").textContent = `Recorded at ${when} · outcome pending`;
    $("action-success").hidden = false;
    loadAudit();
    loadQueue();
  } catch (e) {
    $("confirm-error").textContent = e.message;
    $("confirm-error").hidden = false;
  }
}

async function loadAudit() {
  try {
    const entries = await api("/api/audit?request_id=" + encodeURIComponent(state.selected));
    fillList($("audit-history"), entries.map((e) =>
      `${e.timestamp} · ${e.chosen_action}${e.override ? " (override)" : ""} · copilot: ${e.copilot_decision_type}` +
      (e.reason ? ` · reason: ${e.reason}` : "")), "No actions recorded yet.");
  } catch (e) {
    fillList($("audit-history"), ["Could not load the audit log: " + e.message], "");
  }
}

// ---------------------------------------------------------------- new request (US-6)
const NEW_FIELDS = [
  ["requester_id", "Requester employee ID", "text"], ["product_name", "Product", "text"], ["vendor_name", "Vendor", "text"],
  ["category", "Category", "text"], ["annual_cost_usd", "Annual cost (USD)", "number"], ["user_count", "Users / licences", "number"],
  ["data_access_level", "Data access level", "text"], ["requested_integrations", "Integrations (comma-separated; 'none' for none)", "text"],
  ["urgency", "Urgency", "text"], ["business_justification", "Business justification", "textarea"],
];

function openNewRequest() {
  const box = $("new-fields");
  clear(box);
  for (const [key, label, type] of NEW_FIELDS) {
    const input = type === "textarea" ? el("textarea", { id: "nf-" + key, rows: "3" }) : el("input", { id: "nf-" + key, type });
    box.appendChild(el("label", { for: "nf-" + key, text: label }));
    box.appendChild(input);
  }
  $("new-error").hidden = true;
  $("new-request").showModal();
}

async function submitNewRequest() {
  const body = {};
  for (const [key, , type] of NEW_FIELDS) {
    const raw = $("nf-" + key).value.trim();
    if (!raw) { body[key] = null; continue; }
    if (key === "requested_integrations") body[key] = raw.toLowerCase() === "none" ? [] : raw.split(",").map((s) => s.trim()).filter(Boolean);
    else if (key === "user_count") body[key] = Number.isInteger(Number(raw)) ? Number(raw) : null;
    else if (type === "number") body[key] = Number.isFinite(Number(raw)) ? Number(raw) : null;
    else body[key] = raw;
  }
  try {
    const created = await api("/api/requests", { method: "POST", body: JSON.stringify(body) });
    $("new-request").close();
    await loadQueue();
    selectRequest(created.request_id);
  } catch (e) {
    $("new-error").textContent = "Could not submit: " + e.message;
    $("new-error").hidden = false;
  }
}

// ---------------------------------------------------------------- wiring
$("btn-analyze").addEventListener("click", analyze);
$("btn-retry-analyze").addEventListener("click", analyze);
$("confirm-cancel").addEventListener("click", () => $("confirm").close());
$("confirm-ok").addEventListener("click", confirmAction);
$("btn-new").addEventListener("click", openNewRequest);
$("new-cancel").addEventListener("click", () => $("new-request").close());
$("new-submit").addEventListener("click", submitNewRequest);
loadHealth();
loadQueue();
