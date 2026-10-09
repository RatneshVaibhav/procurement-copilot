from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mock_api import launcher
from src.config import get_settings
from src.contracts import ProcurementDecision
from src.solution import handle_request


def norm(value: object) -> str:
    return str(value).strip().lower()


def list_text(items: list[object]) -> list[str]:
    return [norm(x) for x in items]


def group_present(items: list[object], group: list[str]) -> bool:
    texts = list_text(items)
    return any(any(norm(token) in item for item in texts) for token in group)


def evaluate(decision: ProcurementDecision, expectations: dict) -> list[str]:
    failures: list[str] = []

    for group in expectations.get('required_approvals_any_groups', []):
        if not group_present(decision.required_approvals, group):
            failures.append(f"approval missing (expected one of: {group})")

    for group in expectations.get('risk_flags_any_groups', []):
        if not group_present(decision.risk_flags, group):
            failures.append(f"risk flag missing (expected one of: {group})")

    for group in expectations.get('missing_information_any_groups', []):
        if not group_present(decision.missing_information, group):
            failures.append(f"missing-info item absent (expected one of: {group})")

    for token in expectations.get('risk_flags_must_not_contain', []):
        if group_present(decision.risk_flags, [token]):
            failures.append(f"unexpected risk flag containing: {token}")

    max_missing = expectations.get('max_missing_information')
    if max_missing is not None and len(decision.missing_information) > max_missing:
        failures.append(f"too many missing-information items: {len(decision.missing_information)} > {max_missing}")

    min_evidence = expectations.get('min_evidence_items', 0)
    if len(decision.evidence) < min_evidence:
        failures.append(f"insufficient evidence items: {len(decision.evidence)} < {min_evidence}")

    expected_human = expectations.get('human_review_required')
    if expected_human is not None and decision.human_review_required != expected_human:
        failures.append(f"human_review_required expected {expected_human}")

    return failures


def ensure_mock_api():
    """F1: start the mock API if it is unreachable and the URL host is local (D-07.2)."""
    base_url = get_settings().vendor_risk_base_url
    if launcher.is_healthy(base_url):
        return None
    if not launcher.is_local(base_url):
        print(f"WARNING: vendor-risk API at {base_url} is unreachable and not local; not starting the mock.")
        return None
    port = launcher.port_of(base_url)
    print(f"Vendor-risk API not reachable at {base_url}; starting the mock on port {port} ...")
    proc = launcher.start(port, quiet=True)
    try:
        launcher.wait_for_api(f"{base_url}/health", proc, label="Mock vendor-risk API")
    except RuntimeError as exc:
        launcher.stop(proc)
        print(f"ERROR: {exc}\nCannot run the public cases without the vendor-risk API.")
        sys.exit(2)
    return proc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--architecture', choices=['single','staged'], default='single')
    args = parser.parse_args()

    mock_proc = ensure_mock_api()
    try:
        ok = run(args)
    finally:
        launcher.stop(mock_proc)
    # D-08: exit non-zero when any case fails or errors.
    sys.exit(0 if ok else 1)


def run(args) -> bool:
    cases = json.loads((ROOT/'evals'/'public_cases.json').read_text(encoding='utf-8'))
    rows = []
    print(f"\nPublic evaluation - architecture={args.architecture}\n")

    for case in cases:
        start = time.perf_counter()
        try:
            raw = handle_request(case['request_id'], architecture=args.architecture)
            decision = raw if isinstance(raw, ProcurementDecision) else ProcurementDecision.model_validate(raw)
            latency_ms = (time.perf_counter() - start) * 1000
            failures = evaluate(decision, case['expectations'])
            passed = not failures
            tel = decision.telemetry
            print(f"{'PASS' if passed else 'FAIL'}  {case['case_id']}  {case['title']}  ({latency_ms:.0f} ms)")
            for f in failures:
                print(f"      - {f}")
            rows.append({
                'case_id':case['case_id'], 'request_id':case['request_id'], 'architecture':args.architecture,
                'passed_minimum_checks':passed, 'latency_ms':round(latency_ms,1),
                'llm_calls': tel.llm_calls if tel else '', 'tool_calls': tel.tool_calls if tel else '',
                'failures':' | '.join(failures)
            })
        except NotImplementedError as exc:
            print(f"STOP  {exc}")
            return False
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            print(f"ERROR {case['case_id']}  {type(exc).__name__}: {exc}")
            rows.append({
                'case_id':case['case_id'], 'request_id':case['request_id'], 'architecture':args.architecture,
                'passed_minimum_checks':False, 'latency_ms':round(latency_ms,1),
                'llm_calls':'', 'tool_calls':'', 'failures':f"ERROR: {type(exc).__name__}: {exc}"
            })

    if rows:
        out_dir = ROOT/'evals'/'results'
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir/f"public_{args.architecture}.csv"
        with out.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader(); writer.writerows(rows)
        passed = sum(1 for r in rows if r['passed_minimum_checks'])
        print(f"\nMinimum checks passed: {passed}/{len(rows)}")
        print(f"Results written to: {out.relative_to(ROOT)}")
    return bool(rows) and all(r['passed_minimum_checks'] for r in rows)


if __name__ == '__main__':
    main()
