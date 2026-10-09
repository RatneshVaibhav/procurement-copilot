---
name: phase
description: Run one PLAN.md phase with the spec-driven loop, log it, and continue to the next phase (D-11).
disable-model-invocation: true
argument-hint: "[phase-number]"
---

Run Phase $ARGUMENTS of PLAN.md.

docs/DECISIONS.md overrides the spec files; do not flag behaviour that DECISIONS.md requires.

1. Re-read docs/DECISIONS.md. Read the PLAN.md section for Phase $ARGUMENTS and only the spec sections it lists (T = docs/SPEC_TECHNICAL.md, D = docs/SPEC_V2_DELTA.md, F = docs/SPEC_FUNCTIONAL.md). Where D and T differ, D wins.
2. Print the task list and the files you expect to touch, then start.
3. Work one task at a time: implement it, write or update its test, run the relevant tests. Do not move on with a failing test.
4. Follow CLAUDE.md hard rules and LLM budget rules. Make real LLM calls only where this phase's checks ask for them.
5. Run all of this phase's checks.
6. Delegate the phase diff to the diff-reviewer subagent. Fix any FAIL that is within this phase's scope; list the rest.
7. Commit with the message "phase $ARGUMENTS: <short summary>". Do not push.
8. Append 5–10 lines to docs/BUILD_LOG.md: summary; files touched; test output (counts and any failures); diff-reviewer verdict; deviations from spec and why; open questions. Add this phase's "Human:" step from PLAN.md to the "Human checklist" at the end of BUILD_LOG.md.
9. Continue straight into the next phase (D-11). Pause only for the four D-11 reasons in docs/DECISIONS.md. For anything else, choose the most conservative option, record it in docs/DECISIONS.md as "D-1x (proposed)", and keep going.
