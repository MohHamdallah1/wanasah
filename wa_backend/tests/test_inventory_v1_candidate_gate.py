"""Fail-closed provenance/report checks, independent of app/runtime/database."""
import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from inventory_v1_candidate_gate import BASE, COUNTS, exact_sha, final_verdict, verify_report

CANDIDATE = "c" * 40
HARNESS = "d" * 40


def reports():
    return [
        {"kind": kind, "mode": mode, "cases": count, "harness_sha": HARNESS,
         "source_sha": BASE if mode == "baseline" else CANDIDATE,
         "verified": True, "skipped": 0,
         "failures": (9 if kind == "postgres" else 4) if mode == "baseline" else 0,
         "negative_evidence_verified": mode == "baseline"}
        for (kind, mode), count in COUNTS.items()
    ]


class CandidateGateTests(unittest.TestCase):
    def test_only_complete_same_candidate_reports_can_pass(self):
        result = final_verdict(CANDIDATE, HARNESS, reports())
        self.assertEqual(result["candidate_sha"], CANDIDATE)
        self.assertEqual(result["verdict"], "PASS")

    def test_missing_candidate_branch_name_and_truncated_sha_fail(self):
        for value in ("", "main", "c" * 7, "0" * 40, CANDIDATE + "; echo unsafe"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exact_sha(value)

    def test_worker_mix_wrong_harness_missing_and_duplicate_reports_fail(self):
        changes = []
        mixed = reports()
        mixed[2]["source_sha"] = "e" * 40
        changes.append(mixed)
        other_harness = reports()
        other_harness[3]["harness_sha"] = "f" * 40
        changes.append(other_harness)
        changes.append(reports()[:2])
        duplicate = reports()
        duplicate[3] = copy.deepcopy(duplicate[2])
        changes.append(duplicate)
        for value in changes:
            with self.subTest(value=value), self.assertRaises(AssertionError):
                final_verdict(CANDIDATE, HARNESS, value)

    def test_unverified_failed_skipped_or_partial_candidate_cannot_pass(self):
        for field, value in (("verified", False), ("failures", 1), ("skipped", 1), ("cases", 1)):
            modified = reports()
            modified[2][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                final_verdict(CANDIDATE, HARNESS, modified)

    def check_xml(self, root, code=0):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "junit.xml"
            ET.ElementTree(root).write(path, encoding="unicode")
            return verify_report(path, "postgres", "candidate", code)

    def good_xml(self):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite")
        for index in range(23):
            name = ("test_financial_lost_response_requires_bound_original_success_replay"
                    if index == 0 else f"contract_{index}")
            ET.SubElement(suite, "testcase", classname="combined", name=name)
        return root

    def test_actual_junit_failure_error_skip_and_duplicate_are_rejected(self):
        for status in ("failure", "error", "skipped"):
            root = self.good_xml()
            ET.SubElement(root.find(".//testcase"), status)
            with self.subTest(status=status), self.assertRaises(AssertionError):
                self.check_xml(root, 1 if status == "failure" else 0)
        root = self.good_xml()
        cases = root.findall(".//testcase")
        cases[-1].attrib.update(cases[0].attrib)
        with self.assertRaises(AssertionError):
            self.check_xml(root)

    def test_financial_case_and_all_cases_must_really_execute(self):
        root = self.good_xml()
        root.find(".//testcase").set("name", "omitted_financial_replay")
        with self.assertRaises(AssertionError):
            self.check_xml(root)
        root = self.good_xml()
        root.find("testsuite").remove(root.findall(".//testcase")[-1])
        with self.assertRaises(AssertionError):
            self.check_xml(root)

    def test_baseline_ordinary_infrastructure_failure_is_not_negative_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.xml"
            root = ET.Element("testsuites")
            suite = ET.SubElement(root, "testsuite")
            for index in range(13):
                case = ET.SubElement(suite, "testcase", name=f"broken_{index}")
                if index < 9:
                    ET.SubElement(case, "failure", message="ImportError")
            ET.ElementTree(root).write(path, encoding="unicode")
            with self.assertRaises(AssertionError):
                verify_report(path, "postgres", "baseline", 1)
