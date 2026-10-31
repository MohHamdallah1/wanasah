"""Cheap policy regression; no inventory HTTP mocks or database fixture."""
import contextlib
import io
import os
from pathlib import Path
import re
import subprocess
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

WORKFLOW = Path(".github/workflows/live-stock-v1-operational-browser.yml").read_text()
CALLER = Path(".github/workflows/live-stock-physical-custody-consumers.yml").read_text()
BLOCK = WORKFLOW.split("- name: Prove integrated-main runtime and historical contract mismatch", 1)[1]
SOURCE = textwrap.dedent(re.search(r"python - <<'PY'\n(.*?)\n          PY", BLOCK, re.S).group(1))
BASE, FUTURE = "a" * 40, "b" * 40
VALID = '"vehicle_quantity_scope" "total_quantity_scope"'
OLD = '"vehicle_quantity": canonical_quantity(vehicle_total)'


class WorkflowContracts(unittest.TestCase):
    def preflight(self, *, changed=True, backend=FUTURE, explicit="", accepted="", compatible=True):
        frontend = FUTURE if changed else BASE

        def git(args, **_):
            cmd = args[1:]
            if cmd == ["rev-parse", "HEAD"]:
                return frontend
            if cmd == ["-C", "backend-under-test", "rev-parse", "HEAD"]:
                return backend
            if cmd[0] == "merge-base":
                return BASE
            if cmd[0] == "show":
                return OLD
            if cmd[0] == "rev-parse" and cmd[1].endswith(":wa_backend"):
                return "base-tree" if cmd[1].startswith(BASE) else "future-tree"
            raise AssertionError(args)

        env = dict(BACKEND_REF=explicit, ACCEPTED_MAIN_REF=accepted, PR_BASE_REF=BASE)
        out = io.StringIO()
        with patch.dict(os.environ, env), patch.object(subprocess, "check_output", side_effect=git), \
             patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=int(changed))), \
             patch.object(Path, "read_text", return_value=VALID if compatible else OLD), \
             patch.object(Path, "write_text"), contextlib.redirect_stdout(out):
            exec(compile(SOURCE, "<actual-workflow-preflight>", "exec"), {})
        return out.getvalue()

    def test_automatic_caller_has_no_historical_pins(self):
        inputs = CALLER.split("    with:\n", 1)[1]
        self.assertNotIn("backend_ref:", inputs)
        self.assertNotIn("accepted_main_ref:", inputs)
        self.assertIn("github.event.pull_request.head.sha || github.sha", WORKFLOW)
        self.assertIn("  workflow_dispatch:\n    inputs:\n", WORKFLOW)

    def test_future_production_change_passes_with_matching_default_heads(self):
        self.assertIn('"runtime_matches_main": false', self.preflight())

    def test_accidental_peer_overlay_fails_without_explicit_pin(self):
        with self.assertRaisesRegex(AssertionError, "matching PR frontend/backend"):
            self.preflight(backend=BASE)

    def test_intentional_unchanged_pinned_main_audit_passes(self):
        self.preflight(changed=False, backend=BASE, explicit=BASE, accepted=BASE)

    def test_intentional_pinned_main_audit_rejects_changed_runtime(self):
        with self.assertRaisesRegex(AssertionError, "unchanged accepted runtime"):
            self.preflight(explicit=FUTURE, accepted=BASE)

    def test_incompatible_current_api_contract_still_fails(self):
        with self.assertRaises(AssertionError):
            self.preflight(compatible=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
