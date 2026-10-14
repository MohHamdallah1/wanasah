"""Focused unit and contract tests for Wanasah Windows Dev Doctor.

Requires no live database, network, or background worker processes.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.wanasah_doctor_probe import (  # noqa: E402
    aggregate_results,
    check_requirements,
    classify_health_endpoints,
    classify_pg_error,
    classify_port_state,
    classify_ready_probe_attempts,
    compute_exit_code,
    detect_localhost_loopback_risk,
    evaluate_backend_db_env,
    is_alembic_ini_url_blank,
    is_onedrive_path,
    parse_dotenv_file,
    parse_postgres_dsn,
    redact_secrets,
    resolve_alembic_repo_heads,
    run_probe_cli,
    sanitize_dsn,
    validate_powershell_script_contract,
)


class DsnAndSecretRedactionTests(unittest.TestCase):
    def test_sanitize_dsn_redacts_password_and_preserves_target(self) -> None:
        raw = "postgresql+asyncpg://wanasah_app:SuperSecretPass!99@127.0.0.1:5432/velotrack_db"
        sanitized = sanitize_dsn(raw)
        self.assertEqual(
            sanitized,
            "postgresql+asyncpg://wanasah_app:***@127.0.0.1:5432/velotrack_db",
        )
        self.assertNotIn("SuperSecretPass", sanitized)

    def test_sanitize_dsn_redacts_query_string_secrets(self) -> None:
        raw = (
            "postgresql://wanasah_app:my_pass@localhost:5432/velotrack_db"
            "?sslmode=require&password= leaked_q_pass &api_key=tok123"
        )
        sanitized = sanitize_dsn(raw)
        self.assertNotIn("my_pass", sanitized)
        self.assertNotIn("leaked_q_pass", sanitized)
        self.assertNotIn("tok123", sanitized)
        self.assertIn("sslmode=require", sanitized)

    def test_malformed_dsn_never_echoes_embedded_secret(self) -> None:
        malformed = "not-a-valid-url-with-embedded-secret-value-12345"
        sanitized = sanitize_dsn(malformed)
        self.assertEqual(sanitized, "<malformed-dsn-redacted>")
        self.assertNotIn("secret-value-12345", sanitized)

        parsed = parse_postgres_dsn(malformed)
        self.assertFalse(parsed["valid"])
        self.assertNotIn("secret-value-12345", str(parsed))

    def test_redact_secrets_scrubs_keys_passwords_and_jwts(self) -> None:
        sample_jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        raw_text = (
            f"SECRET_KEY=MyUltraSecretKeyValue1234567890AbCdEf "
            f"PGPASSWORD=pg_secret_987 "
            f"Authorization: Bearer {sample_jwt} "
            f"dsn=postgresql://admin:dbpass123@127.0.0.1:5432/velotrack_db"
        )
        cleaned = redact_secrets(raw_text)
        self.assertNotIn("MyUltraSecretKeyValue1234567890AbCdEf", cleaned)
        self.assertNotIn("pg_secret_987", cleaned)
        self.assertNotIn(sample_jwt, cleaned)
        self.assertNotIn("dbpass123", cleaned)
        self.assertIn("postgresql://admin:***@127.0.0.1:5432/velotrack_db", cleaned)


class OneDrivePathDetectionTests(unittest.TestCase):
    def test_detects_standard_and_business_onedrive_paths(self) -> None:
        self.assertTrue(
            is_onedrive_path(r"C:\Users\admin\OneDrive\Desktop\wanasah", env={})
        )
        self.assertTrue(
            is_onedrive_path(
                r"C:\Users\admin\OneDrive - Wanasah Co\Projects\wanasah",
                env={},
            )
        )

    def test_detects_onedrive_via_environment_root(self) -> None:
        env = {"OneDriveCommercial": r"D:\SyncedWorkspace\CompanyRoot"}
        self.assertTrue(
            is_onedrive_path(
                r"D:\SyncedWorkspace\CompanyRoot\repos\wanasah",
                env=env,
            )
        )

    def test_normal_local_path_is_not_flagged(self) -> None:
        self.assertFalse(
            is_onedrive_path(r"C:\dev\wanasah", env={"OneDrive": r"C:\Users\dev\OneDrive"})
        )


class StatusAggregationAndExitCodeTests(unittest.TestCase):
    def test_exit_code_zero_when_no_blocking_failures(self) -> None:
        results = [
            {"status": "PASS", "action": ""},
            {"status": "WARN", "action": "Replace localhost with 127.0.0.1."},
            {"status": "INFO", "action": "Start Backend API when needed."},
        ]
        summary = aggregate_results(results)
        self.assertEqual(
            summary["counts"],
            {"PASS": 1, "WARN": 1, "FAIL": 0, "INFO": 1},
        )
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(
            compute_exit_code(summary["counts"], strict=True),
            1,
        )

    def test_exit_code_nonzero_and_actions_prioritize_failures_first(self) -> None:
        results = [
            {"status": "WARN", "action": "Warn action 1"},
            {"status": "FAIL", "action": "Fail action 1"},
            {"status": "INFO", "action": "Info action 1"},
            {"status": "FAIL", "action": "Fail action 2"},
            {"status": "FAIL", "action": "Fail action 1"},  # duplicate
            {"status": "WARN", "action": "Warn action 2"},
        ]
        summary = aggregate_results(results)
        self.assertEqual(summary["exit_code"], 1)
        self.assertEqual(
            summary["next_actions"],
            ["Fail action 1", "Fail action 2", "Warn action 1"],
        )


class PostgresAndPortClassificationTests(unittest.TestCase):
    def test_postgres_distinguishes_four_failure_states(self) -> None:
        bins_missing = classify_pg_error(
            "Connection refused",
            binaries_present=False,
            port_listening=False,
        )
        self.assertEqual(bins_missing["category"], "BINARIES_MISSING")
        self.assertEqual(bins_missing["status"], "FAIL")

        server_down = classify_pg_error(
            "Connection refused",
            binaries_present=True,
            port_listening=False,
        )
        self.assertEqual(server_down["category"], "SERVER_NOT_RUNNING")
        self.assertEqual(server_down["status"], "FAIL")

        auth_err = classify_pg_error(
            'FATAL: password authentication failed for user "wanasah_app" (SQLSTATE 28P01)',
            binaries_present=True,
            port_listening=True,
        )
        self.assertEqual(auth_err["category"], "AUTH_OR_CONFIG_ERROR")
        self.assertEqual(auth_err["status"], "FAIL")

        db_missing = classify_pg_error(
            "FATAL: database wanasah_local does not exist (SQLSTATE 3D000)",
            binaries_present=True,
            port_listening=True,
        )
        self.assertEqual(db_missing["category"], "DATABASE_MISSING")
        self.assertEqual(db_missing["status"], "FAIL")

    def test_port_classification_handles_free_expected_and_unexpected(self) -> None:
        p5432_free = classify_port_state(5432, listening=False)
        self.assertEqual(p5432_free["status"], "FAIL")

        p5432_ok = classify_port_state(
            5432, listening=True, process_name="postgres", pid=4120
        )
        self.assertEqual(p5432_ok["status"], "PASS")

        p8000_free = classify_port_state(8000, listening=False)
        self.assertEqual(p8000_free["status"], "INFO")

        p8000_conflict = classify_port_state(
            8000, listening=True, process_name="java", pid=9999
        )
        self.assertEqual(p8000_conflict["status"], "FAIL")

        p8080_ok = classify_port_state(
            8080, listening=True, process_name="node", pid=3210
        )
        self.assertEqual(p8080_ok["status"], "PASS")

        p8080_conflict = classify_port_state(
            8080, listening=True, process_name="httpd", pid=5555
        )
        self.assertEqual(p8080_conflict["status"], "FAIL")

    def test_health_classification_does_not_fail_when_backend_stopped(self) -> None:
        stopped = classify_health_endpoints(
            port_listening=False,
            health_status=None,
            health_body=None,
            ready_status=None,
            ready_body=None,
        )
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["status"], "INFO")

        healthy = classify_health_endpoints(
            port_listening=True,
            health_status=200,
            health_body={"status": "alive"},
            ready_status=200,
            ready_body={"status": "ready"},
        )
        self.assertEqual([c["status"] for c in healthy], ["PASS", "PASS"])

        unready = classify_health_endpoints(
            port_listening=True,
            health_status=200,
            health_body={"status": "alive"},
            ready_status=503,
            ready_body={"message": "Database connection failed"},
        )
        self.assertEqual([c["status"] for c in unready], ["PASS", "FAIL"])


class ProductImportAndRepositoryContractTests(unittest.TestCase):
    def test_windows_localhost_loopback_risk_detected(self) -> None:
        at_risk = detect_localhost_loopback_risk(
            "postgresql+asyncpg://wanasah_app:secret@localhost:5432/velotrack_db",
            platform_name="win32",
        )
        self.assertTrue(at_risk["at_risk"])
        self.assertEqual(at_risk["recommended_host"], "127.0.0.1")

        safe = detect_localhost_loopback_risk(
            "postgresql+asyncpg://wanasah_app:secret@127.0.0.1:5432/velotrack_db",
            platform_name="win32",
        )
        self.assertFalse(safe["at_risk"])

    def test_missing_or_mismatched_packages_detected(self) -> None:
        with TemporaryDirectory() as tmp:
            req_path = Path(tmp) / "requirements.txt"
            req_path.write_text(
                "nonexistent-wanasah-pkg==9.9.9\n",
                encoding="utf-8",
            )
            res = check_requirements(req_path)
            self.assertFalse(res["ok"])
            self.assertEqual(res["missing"], ["nonexistent-wanasah-pkg==9.9.9"])

    def test_alembic_static_head_matches_repository(self) -> None:
        versions_dir = BACKEND_ROOT / "alembic" / "versions"
        head_info = resolve_alembic_repo_heads(versions_dir)
        self.assertTrue(head_info["ok"])
        self.assertEqual(head_info["heads"], ["b7a4c2d9e105"])
        self.assertEqual(head_info["count"], 76)

    def test_probe_cli_redacts_secrets_and_detects_env_conflicts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "wa_backend"
            (backend / "alembic" / "versions").mkdir(parents=True)
            (backend / "alembic.ini").write_text(
                "[alembic]\nsqlalchemy.url =\n",
                encoding="utf-8",
            )
            (backend / "requirements.txt").write_text("", encoding="utf-8")
            (backend / ".env").write_text(
                "SECRET_KEY=FileSecretKey1234567890AbCdEfGhIjKlMnOp\n"
                "DATABASE_URL=postgresql+asyncpg://wanasah_app:FileSecretPass@localhost:5432/velotrack_db\n"
                "DATABASE_URL_MIGRATION=postgresql://wanasah_app:FileSecretPass@localhost:5432/velotrack_db\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "DATABASE_URL": "postgresql+asyncpg://wanasah_app:InheritedSecretPass@localhost:5432/velotrack_db"
                },
                clear=True,
            ):
                output = run_probe_cli(
                    root,
                    binaries_present=True,
                    port_5432_listening=False,
                )
            serialized = str(output)
            self.assertNotIn("FileSecretKey1234567890AbCdEfGhIjKlMnOp", serialized)
            self.assertNotIn("FileSecretPass", serialized)
            self.assertNotIn("InheritedSecretPass", serialized)
            self.assertIn("DATABASE_URL", output["env"]["env_conflicts"])
            self.assertTrue(output["env"]["localhost_risk"]["at_risk"])

    def test_powershell_doctor_script_passes_static_safety_and_structure_audit(self) -> None:
        ps1_path = REPO_ROOT / "ops" / "development" / "wanasah_doctor.ps1"
        issues = validate_powershell_script_contract(ps1_path)
        self.assertEqual(issues, [])


class WindowsLeadReviewRegressionTests(unittest.TestCase):
    def test_powershell_source_is_strict_ascii_and_rejects_non_ascii_em_dash(self) -> None:
        ps1_path = REPO_ROOT / "ops" / "development" / "wanasah_doctor.ps1"
        raw = ps1_path.read_bytes()
        self.assertTrue(
            all(b in (9, 10, 13) or (32 <= b <= 126) for b in raw),
            "wanasah_doctor.ps1 must contain only 7-bit ASCII characters for Windows PowerShell 5.1",
        )
        with TemporaryDirectory() as tmp:
            bad_ps1 = Path(tmp) / "bad_doctor.ps1"
            bad_ps1.write_bytes(raw + b" # em-dash \xe2\x80\x94 hazard\n")
            issues = validate_powershell_script_contract(bad_ps1)
            self.assertTrue(
                any("Non-ASCII byte" in item for item in issues),
                f"Expected Non-ASCII byte rejection, got {issues}",
            )

    def test_alembic_ini_empty_sqlalchemy_url_followed_by_section_header_is_pass(self) -> None:
        crlf_ini = (
            "[alembic]\r\n"
            "script_location = %(here)s/alembic\r\n"
            "sqlalchemy.url =\r\n"
            "\r\n"
            "[post_write_hooks]\r\n"
        )
        lf_spaces_ini = (
            "[alembic]\n"
            "sqlalchemy.url =   \t  \n"
            "[post_write_hooks]\n"
        )
        non_empty_ini = (
            "[alembic]\r\n"
            "sqlalchemy.url = postgresql://user:pass@127.0.0.1:5432/db\r\n"
            "[post_write_hooks]\r\n"
        )
        self.assertTrue(is_alembic_ini_url_blank(crlf_ini))
        self.assertTrue(is_alembic_ini_url_blank(lf_spaces_ini))
        self.assertFalse(is_alembic_ini_url_blank(non_empty_ini))

    def test_general_db_name_wanasah_local_passes_without_velotrack_warning(self) -> None:
        checks = evaluate_backend_db_env(
            "postgresql+asyncpg://wanasah_app:secret@127.0.0.1:5432/wanasah_local",
            None,
        )
        statuses = [c["status"] for c in checks]
        self.assertNotIn("WARN", statuses)
        self.assertNotIn("FAIL", statuses)
        db_check = checks[0]
        self.assertEqual(db_check["status"], "PASS")
        self.assertIn("wanasah_local", db_check["detail"])
        self.assertEqual(db_check["action"], "")

    def test_absent_database_url_migration_is_classified_as_info_with_no_action(self) -> None:
        checks = evaluate_backend_db_env(
            "postgresql+asyncpg://wanasah_app:secret@127.0.0.1:5432/wanasah_local",
            "",
        )
        mig_check = [c for c in checks if c["name"] == "DATABASE_URL_MIGRATION configuration"][0]
        self.assertEqual(mig_check["status"], "INFO")
        self.assertEqual(mig_check["action"], "")
        summary = aggregate_results(checks)
        self.assertEqual(summary["counts"]["WARN"], 0)
        self.assertEqual(summary["counts"]["FAIL"], 0)
        self.assertEqual(summary["next_actions"], [])

    def test_ready_probe_retries_once_on_transient_timeout_and_fails_on_persistent_error(self) -> None:
        transient_recovered = classify_ready_probe_attempts(
            [
                (None, None, "The operation has timed out."),
                (200, {"status": "ready"}, None),
            ]
        )
        self.assertEqual(transient_recovered["status"], "PASS")
        self.assertIn("succeeded on retry 2/2", transient_recovered["detail"])

        persistent_fail = classify_ready_probe_attempts(
            [
                (None, None, "The operation has timed out."),
                (503, {"message": "Database connection failed"}, None),
            ]
        )
        self.assertEqual(persistent_fail["status"], "FAIL")
        self.assertIn("after 2 attempt(s)", persistent_fail["detail"])


    def test_run_probe_cli_with_missing_alembic_ini_does_not_throw(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "wa_backend"
            (backend / "alembic" / "versions").mkdir(parents=True)
            (backend / "requirements.txt").write_text("", encoding="utf-8")
            (backend / ".env").write_text(
                "SECRET_KEY=ValidSecretKey1234567890AbCdEfGhIjKlMnOp\n"
                "DATABASE_URL=postgresql+asyncpg://wanasah_app:SecretPass@127.0.0.1:5432/wanasah_local\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                payload = run_probe_cli(
                    root,
                    binaries_present=True,
                    port_5432_listening=False,
                )
            self.assertFalse(payload["alembic"]["alembic_ini_exists"])
            self.assertFalse(payload["alembic"]["alembic_ini_url_blank"])
            self.assertTrue(payload["env"]["database_url"]["valid"])
            self.assertEqual(payload["env"]["secret_key_status"], "PASS")

    def test_database_missing_classification_does_not_reference_velotrack_db(self) -> None:
        res = classify_pg_error(
            "FATAL: database wanasah_local does not exist (SQLSTATE 3D000)",
            binaries_present=True,
            port_listening=True,
        )
        self.assertEqual(res["category"], "DATABASE_MISSING")
        self.assertEqual(res["status"], "FAIL")
        self.assertNotIn("velotrack_db", res["summary"])
        self.assertNotIn("velotrack_db", res["action"])

    def test_server_not_running_guidance_supports_service_and_custom_cluster(self) -> None:
        port_closed = classify_pg_error(
            "Connection refused",
            binaries_present=True,
            port_listening=False,
        )
        self.assertEqual(port_closed["category"], "SERVER_NOT_RUNNING")
        self.assertIn("Windows service", port_closed["action"])
        self.assertIn("pg_ctl/custom-cluster", port_closed["action"])

        conn_refused = classify_pg_error(
            "could not connect to server: Connection refused",
            binaries_present=True,
            port_listening=True,
        )
        self.assertEqual(conn_refused["category"], "SERVER_NOT_RUNNING")
        self.assertIn("Windows service", conn_refused["action"])
        self.assertIn("pg_ctl/custom-cluster", conn_refused["action"])

        port_state = classify_port_state(5432, listening=False)
        self.assertEqual(port_state["status"], "FAIL")
        self.assertIn("Windows service", port_state["action"])
        self.assertIn("pg_ctl/custom-cluster", port_state["action"])


if __name__ == "__main__":
    unittest.main()
