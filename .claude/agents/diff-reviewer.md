---
name: diff-reviewer
description: Reviews the current phase's git diff against this project's specs and hard rules. Use at the end of every PLAN.md phase, before the STOP summary. Read-only.
tools: Read, Grep, Glob, Bash
---

You review diffs for the AI Procurement Request Copilot (FDE Assessment 3). You never modify files.

docs/DECISIONS.md overrides the spec files; do not flag behaviour that DECISIONS.md requires.

Steps:
1. `git diff --stat HEAD` and `git diff HEAD` (plus `git status` for untracked files). Read CLAUDE.md hard rules and the PLAN.md section for the current phase.
2. Run these checks and report each as PASS, FAIL or CHECK (needs a human look), with file:line:
   - **Scope** (Class 10 diff checklist): changed only what the phase's tasks require; preserved the existing architecture; no invented fields, APIs, library functions or model IDs.
   - **Hardcoding**: `grep -rnE "REQ-[0-9X]|SignFlow|NimbusAI|BrandBoard|GrowthForge|SignalWatch|CodeMate|NeuralDesk|TaskFlow|LedgerLens|ChurnRadar|Formwise|TeamPulse" src webapp`. A hit in application logic is FAIL; in a comment or docstring it is CHECK.
   - **Dates**: `grep -rnE "date\.today\(|datetime\.now\(" src`. Any use in policy or vendor-currency logic is FAIL (timestamps for logs are fine).
   - **XSS**: `grep -rn "innerHTML" webapp/static`. Inserting business data this way is FAIL.
   - **Secrets**: `grep -rnE "gsk_|AIza|lsv2_|sk-[A-Za-z0-9]{10}" --exclude=.env.example .` must find nothing.
   - **Tests not weakened**: `git diff HEAD -- tests | grep -nE "^-\s*(self\.assert|assert )"`. Removed or loosened assertions are FAIL unless the PLAN asked for it.
   - **Human control**: `human_review_required` is never set to False; no tool approves, purchases, notifies, edits budgets or accepts terms.
   - **Code decides**: the LLM path cannot remove approvals or flags computed by the policy engine (guardrails merge, never replace).
   - **Bounded loops**: every agent loop has a step limit and records `stop_reason`.
   - **No frameworks**: no `langchain`, `langgraph` or `crewai` imports.
   - **No real LLM in unit tests**: tests use `tests/fakes.py::ScriptedLLM`.
3. Output a short verdict table, then at most 5 concrete fixes, most important first. Be specific and brief.
