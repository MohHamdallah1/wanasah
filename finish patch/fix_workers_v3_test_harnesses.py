from pathlib import Path

ROOT = Path(__file__).resolve().parent

PATCH_FILE = ROOT / "workers_monitor_correctness_v3.py"
GATE_FILE = ROOT / "workers_final_freeze_gate_v3.py"

OLD = '        "NO_WORKFLOW_MUTATION_HANDSHAKE": (\n            ".status =" not in handshake\n            and "force_cancel_handshake" not in handshake\n            and "apply_inventory_movements" not in handshake\n        ),\n        "NO_WORKFLOW_MUTATION_SESSION": (\n            ".end_time =" not in session\n            and ".is_settled =" not in session\n            and "apply_inventory_movements" not in session\n        ),\n'
NEW = '        "NO_WORKFLOW_MUTATION_HANDSHAKE": (\n            re.search(r"\\.status\\s*=(?!=)", handshake) is None\n            and "force_cancel_handshake" not in handshake\n            and "apply_inventory_movements" not in handshake\n        ),\n        "NO_WORKFLOW_MUTATION_SESSION": (\n            re.search(r"\\.end_time\\s*=(?!=)", session) is None\n            and re.search(r"\\.is_settled\\s*=(?!=)", session) is None\n            and "apply_inventory_movements" not in session\n        ),\n'


def fail(msg: str) -> None:
    raise SystemExit(f"FIX_ABORTED: {msg}")


if not PATCH_FILE.exists():
    fail("workers_monitor_correctness_v3.py not found in project root.")

text = PATCH_FILE.read_text(encoding="utf-8")

if NEW in text:
    print("ALREADY_FIXED=workers_monitor_correctness_v3.py")
else:
    if text.count(OLD) != 1:
        fail(
            "Expected false-positive verifier block exactly once in "
            "workers_monitor_correctness_v3.py"
        )
    if "import re\n" not in text:
        text = text.replace("import ast\n", "import ast\nimport re\n", 1)
    text = text.replace(OLD, NEW, 1)
    PATCH_FILE.write_text(text, encoding="utf-8")
    print("FIXED=workers_monitor_correctness_v3.py")


if not GATE_FILE.exists():
    fail("workers_final_freeze_gate_v3.py not found in project root.")

gate = GATE_FILE.read_text(encoding="utf-8")

if "import ast\n" in gate:
    print("ALREADY_FIXED=workers_final_freeze_gate_v3.py")
else:
    anchor = "import asyncio\n"
    if gate.count(anchor) != 1:
        fail("Could not locate import anchor in workers_final_freeze_gate_v3.py")
    gate = gate.replace(anchor, anchor + "import ast\n", 1)
    GATE_FILE.write_text(gate, encoding="utf-8")
    print("FIXED=workers_final_freeze_gate_v3.py")

print("WORKERS_V3_TEST_HARNESSES_FIX=OK")
