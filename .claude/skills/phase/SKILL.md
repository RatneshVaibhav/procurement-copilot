---
name: phase
description: Run one PLAN.md phase with the spec-driven loop, then stop for human review.
disable-model-invocation: true
argument-hint: "[phase-number]"
---

Run Phase $ARGUMENTS of PLAN.md.

1. Read the PLAN.md section for Phase $ARGUMENTS and only the spec sections it lists (T = docs/SPEC_TECHNICAL.md, D = docs/SPEC_V2_DELTA.md, F = docs/SPEC_FUNCTIONAL.md). Where D and T differ, D wins.
2. Print the task list and the files you expect to touch, then start.
3. Work one task at a time: implement it, write or update its test, run the relevant tests. Do not move on with a failing test.
4. Follow CLAUDE.md hard rules and LLM budget rules. Make real LLM calls only where this phase's checks ask for them.
5. Run all of this phase's checks.
6. Delegate the phase diff to the diff-reviewer subagent. Fix any FAIL that is within this phase's scope; list the rest.
7. Commit with the message "phase $ARGUMENTS: <short summary>". Do not push.
8. STOP and print: summary; files touched; test output (counts and any failures); diff-reviewer verdict; deviations from spec and why; open questions; and this phase's "Human:" step from PLAN.md. Then wait.
