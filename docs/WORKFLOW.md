# Workflow, value and success metrics

Companion to `README.md` §3. Numbers come from `evals/results/summary.md` (Gemini `gemini-3.5-flash-lite`, primary eval) unless another file is named. Nothing here is estimated; metrics without data say so.

## 1. User and decision

- **Primary user:** the procurement reviewer who triages software and service purchase requests.
- **Decision supported:** "What should happen next with this request, and which humans must approve it?" One of: request clarification, use an existing tool, route for specialist review, route for approval.
- **Secondary users:** the requester (submits the form) and the approvers (receive the evidence pack; simulated in the MVP).

## 2. Before: the manual workflow

| Step | What the reviewer does by hand | What goes wrong |
|---|---|---|
| 1 | Read the request, chase missing fields by email | Incomplete requests reach approvers |
| 2 | Search the catalog and purchase history for tools that already do this | Duplicate purchases; overlap missed |
| 3 | Look up the department's remaining budget | Shortfalls found late |
| 4 | Check the vendor registry, then the vendor-risk service; compare review dates with the 365-day rule | Expired or conflicting vendor evidence trusted by default |
| 5 | Work out approvers from the cost tiers (policy §4) and the Security/Privacy/Legal triggers (§5–§7) | Inconsistent routing between reviewers |
| 6 | Write a routing note and send it | No record of why; instructions hidden in request text can mislead |

## 3. After: with the copilot

| Step | Who | What happens |
|---|---|---|
| 1 | Requester | Submits the form or the request arrives in the data file; it appears in the queue as `New` |
| 2 | Copilot (code) | Runs the four evidence tools and the deterministic policy engine: thresholds, budget, review currency, registry/API conflicts, Security/Privacy/Legal triggers, required fields, injection scan |
| 3 | Copilot (AI) | Judges whether an existing licensed tool already meets the need, notices data classes implied only by free text, writes the recommendation; it can add a review, never remove one |
| 4 | Reviewer | Reads the recommendation, each approval with its rule and policy section, flags, missing information, evidence with its source, and the "How this was decided" trace |
| 5 | Reviewer | Chooses an action; the consequence is shown first; a reason is required to override the copilot |
| 6 | System | Appends the action to `runtime/audit_log.jsonl`; a mistaken action is revoked with a reason, as a new entry |

Humans keep every approval, every exception and the final routing. No tool can approve, purchase, notify, change a budget or accept terms.

## 4. Value story

- **Consistency:** approvals, flags and missing information come from code, so the same request is routed the same way every time. In the eval, code never had to restore an approval or flag the LLM dropped ("Code corrections per run": 0 for A and B).
- **Safety under bad input:** A passed 3/3 injection cases and 2/2 fault cases (vendor-risk API down, LLM down); every output has `human_review_required = true`.
- **At the rules' floor:** on the first trial A fails nothing that the rules-only workflow passes, on both evaluated models (per-case matrices in `evals/results/summary.md` and `evals/results_qwen/summary.md`); over three trials it dropped below the rules in 2 of 69 runs.
- **Judgement the rules cannot give:** only the AI can say "a licensed tool already covers this" (G-08). The stronger model gets it (`evals/results_qwen/summary.md`: A 1/2 AI-only cases); Flash-Lite gets it in 1 of 3 trials. This value depends on the model.
- **Speed:** one analysis averages 6857.1 ms of active time and 3.3 LLM calls for A. The manual baseline time has not been measured (see §5).

## 5. Success metrics

| Metric | Definition | Target | Current evidence |
|---|---|---|---|
| Required-approval recall | Share of requests where every policy-required approval is in the copilot output | 100% | Met on every golden case except G-23 (personal data implied only by text), for every column |
| Exact routing accuracy | Golden case passes: approvals, flags, missing information and decision all exact | At or above the rules-only workflow, and never below it on any case | A 21/23 in each of 3 trials, rules-only 20/23; on the first trial A fails no case that rules-only passes (2 of 69 runs across all trials, B 11). Held-out (`evals/results_heldout/summary.md`, first trial): A 4/5, rules-only 2/5 |
| Injection resistance | Injection cases flagged with no effect on approvals, flags or decision | 100% | A 3/3 |
| Degraded-evidence handling | Fault cases (service down) handled without a favorable assumption | 100% | A 2/2 |
| Analysis latency | Active time per analysis, excluding provider rate-limit waits | Under 30 s (US-2) | A avg 6857.1 ms |
| Override rate | Share of recorded actions where the reviewer chose differently from the copilot | Tracked weekly; a rising rate means drift | `override` field in `runtime/audit_log.jsonl`; no pilot data yet |
| Time to routing decision | From opening a request to recording an action | Below the manual baseline | Manual baseline not measured; measure it in the pilot first |

## 6. Scope

- **In:** the four decision types, the six required output fields, the four reviewer actions with confirmation and audit, rollback by revoke, compare A vs B, evidence-pack download, the read-only evaluation dashboard.
- **Out (MVP):** real approvals, purchasing, notifications, email or Slack; authentication and roles; editing budgets or the catalog; real vendor APIs; seat-utilisation checks (no data); more than two agents; RAG over the policy.

## 7. Next step before production

A shadow pilot: reviewers keep the manual process while the copilot runs alongside on the same requests. Measure the manual time-to-decision baseline, compare routing, and collect override reasons. Promote when required-approval recall stays at 100% and override reasons show no systematic error. Two known gaps to close first: a deterministic check for personal data implied only by free text (G-23), and repeated trials on a stronger model for the existing-tool judgement (G-08).
