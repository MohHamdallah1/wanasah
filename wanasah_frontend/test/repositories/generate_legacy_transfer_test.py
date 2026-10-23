"""Build a CI-only harness around the exact production compatibility method.

No production constructor/identity/persistence seam is changed for testability.
The generated test is not a second implementation: its method body is copied
verbatim from the checked-out PR head, with fake external dependencies only.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / "lib/repositories/sync_repository.dart").read_text()
start = source.index("  Future<bool> respondToTransfer({")
end = source.index("\n  // ---", start)
method = source[start:end]
assert method.count("Future<bool> respondToTransfer") == 1
assert "rethrow;" in method
template = Path(__file__).with_name("legacy_transfer_compatibility.dart.template").read_text()
assert template.count("@@PRODUCTION_METHOD@@") == 1
target = Path(__file__).with_name("legacy_transfer_compatibility_generated_test.dart")
target.write_text(template.replace("@@PRODUCTION_METHOD@@", method))
print("GENERATED_EXACT_RESPOND_TO_TRANSFER_METHOD=" + str(len(method.splitlines())))
