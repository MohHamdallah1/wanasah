"""Acceptance-owned report verifier; only a supplied combined candidate can PASS."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = "8231ca07f945feb61737e7b4ac6150846cba60a8"
PG_MAIN = "tests/test_inventory_v1_final_closure_acceptance_postgres.py"
PG_COMBINED = "tests/test_inventory_v1_combined_candidate_postgres.py"
UI_MAIN = "src/test/inventory-v1-final-closure-acceptance.test.tsx"
UI_COMBINED = "src/test/inventory-v1-combined-journey.test.tsx"
UI_QUALITY = "src/test/inventory-v1-combined-quality.test.tsx"
COUNTS = {("postgres", "baseline"): 13, ("dashboard", "baseline"): 4,
          ("postgres", "candidate"): 23, ("dashboard", "candidate"): 16}


def exact_sha(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value or "") or value == "0" * 40:
        raise ValueError("COMBINED_CANDIDATE_REQUIRED: supply one full 40-character commit SHA")
    return value


def cases(path):
    root = ET.parse(path).getroot()
    result = root.findall(".//testcase")
    if not result:
        raise AssertionError("No acceptance cases executed")
    if root.findall(".//skipped") or root.findall(".//error"):
        raise AssertionError("Skipped, xfailed or setup-error coverage is not acceptance")
    return result


def verify_report(path, kind, mode, returncode):
    found = cases(path)
    assert len(found) == COUNTS[kind, mode], (kind, mode, len(found))
    identities = [(r.get("classname"), r.get("name")) for r in found]
    assert len(set(identities)) == len(identities), "Duplicate case identities"
    failures = [r for r in found if r.find("failure") is not None]
    if mode == "candidate":
        assert returncode == 0 and not failures, "Combined-candidate acceptance is red"
        if kind == "postgres":
            assert any(r.get("name", "").startswith(
                "test_financial_lost_response_requires_bound_original_success_replay")
                for r in found), "Financial lost-response case is mandatory"
        return {"cases": len(found), "failures": 0, "skipped": 0}
    # Negative controls NEVER qualify as candidate PASS. Verify exact known failures,
    # not merely a nonzero exit (which could hide broken fixtures or imports).
    assert returncode == 1
    if kind == "postgres":
        assert len(failures) == 9 and len(found) - len(failures) == 4
        for case in failures:
            name = case.get("name", "")
            failure = case.find("failure")
            details = failure.get("message", "") + (failure.text or "")
            if name.startswith("test_published_same_location_defaults"):
                assert "TransferDestinationPolicySaveRequest" in details
                assert "quarantine_location_id" in details and "ValidationError" in details
            elif name == "test_financial_close_requires_receiver_handoff_not_only_legacy_seal":
                assert "Financial close accepted a legacy aggregate seal" in details
                assert "200" in details
            elif name.startswith("test_receiver_"):
                assert "RECEIVER_CONTRACT_NOT_IN_CANDIDATE" in details
            else:
                raise AssertionError("Unexpected frozen-baseline failure: " + name)
        assert sum(r.get("name", "").startswith("test_published_same_location_defaults")
                   for r in failures) == 4
        assert sum(r.get("name", "").startswith("test_receiver_") for r in failures) == 4
    else:
        assert len(failures) == 4
        for case in failures:
            name = case.get("name", "")
            failure = case.find("failure")
            details = failure.get("message", "") + (failure.text or "")
            if "Stocktake has no second representative start" in name:
                assert "null" in details
            elif "financial close has cash input but no second stock count" in name:
                assert "3" in details and "length" in details
            else:
                raise AssertionError("Unexpected baseline DOM failure: " + name)
    return {"cases": len(found), "failures": len(failures), "skipped": 0,
            "negative_evidence_verified": True}


def final_verdict(candidate, harness, reports):
    exact_sha(candidate)
    exact_sha(harness)
    assert len(reports) == 4, "Both baseline and combined-candidate reports are required"
    indexed = {(r["kind"], r["mode"]): r for r in reports}
    assert set(indexed) == set(COUNTS), "Missing or duplicate report kind"
    for key, expected_count in COUNTS.items():
        row = indexed[key]
        assert row["verified"] is True and row["harness_sha"] == harness
        assert row["cases"] == expected_count and row["skipped"] == 0
        if row["mode"] == "candidate":
            assert row["source_sha"] == candidate, "Candidate SHA mismatch"
            assert row["failures"] == 0
        else:
            assert row["source_sha"] == BASE and row["negative_evidence_verified"] is True
    return {"verdict": "PASS", "candidate_sha": candidate, "harness_sha": harness,
            "gate": "FINAL_INVENTORY_V1_COMBINED_ACCEPTANCE"}


def run(args):
    source = Path(args.source).resolve()
    exact_sha(args.harness_sha)
    expected = BASE if args.mode == "baseline" else exact_sha(args.candidate_sha)
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                     text=True).strip()
    assert actual == expected, "Source checkout is not the requested exact commit"
    assert os.environ.get("WANASAH_CLOSURE_BASELINE_EVIDENCE", "0") == (
        "1" if args.mode == "baseline" else "0"), "Baseline mode cannot leak into candidate"
    xml = Path(args.output).resolve().with_suffix(".xml")
    xml.parent.mkdir(parents=True, exist_ok=True)
    if args.kind == "postgres":
        files = [PG_MAIN] + ([PG_COMBINED] if args.mode == "candidate" else [])
        command = [sys.executable, "-B", "-m", "pytest", "-o", "addopts=",
                   "-p", "no:cacheprovider", "-q", *files, "--junitxml=" + str(xml)]
        cwd = source / "wa_backend"
    else:
        files = [UI_MAIN] + ([UI_COMBINED, UI_QUALITY] if args.mode == "candidate" else [])
        command = ["npx", "vitest", "run", *files, "--reporter=default", "--reporter=junit",
                   "--outputFile.junit=" + str(xml)]
        cwd = source / "dashboard"
    code = subprocess.run(command, cwd=cwd, check=False).returncode
    record = {"kind": args.kind, "mode": args.mode, "source_sha": actual,
              "harness_sha": args.harness_sha, "verified": False}
    try:
        record.update(verify_report(xml, args.kind, args.mode, code))
        record["verified"] = True
    finally:
        Path(args.output).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("BASELINE_NEGATIVE_EVIDENCE=PASS" if args.mode == "baseline"
          else "COMBINED_" + args.kind.upper() + "=PASS")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--kind", choices=["postgres", "dashboard"], required=True)
    execute.add_argument("--mode", choices=["baseline", "candidate"], required=True)
    execute.add_argument("--source", required=True)
    execute.add_argument("--candidate-sha", default="")
    execute.add_argument("--harness-sha", required=True)
    execute.add_argument("--output", required=True)
    final = commands.add_parser("final")
    final.add_argument("--candidate-sha", required=True)
    final.add_argument("--harness-sha", required=True)
    final.add_argument("--reports", required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args)
    else:
        reports = [json.loads(p.read_text()) for p in Path(args.reports).rglob("*.json")]
        result = final_verdict(args.candidate_sha, args.harness_sha, reports)
        print(json.dumps(result, sort_keys=True))
        print("FINAL_INVENTORY_V1_COMBINED_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
