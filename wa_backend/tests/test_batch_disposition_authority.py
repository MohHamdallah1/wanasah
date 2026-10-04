import inspect
import os

os.environ.setdefault("SECRET_KEY", "BatchDispositionAuthorityTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from services import (
    allowed_batch_disposition_targets,
    change_product_batch_disposition,
)


def test_backend_is_the_single_batch_disposition_transition_authority():
    assert allowed_batch_disposition_targets("RELEASED") == (
        "QUARANTINED",
        "BLOCKED",
        "RECALLED",
    )
    assert allowed_batch_disposition_targets("QUARANTINED") == (
        "RELEASED",
        "BLOCKED",
        "RECALLED",
    )
    assert allowed_batch_disposition_targets("BLOCKED") == ("RECALLED",)
    assert allowed_batch_disposition_targets("RECALLED") == ()

    source = inspect.getsource(change_product_batch_disposition)
    assert "target not in allowed_batch_disposition_targets(current)" in source
    assert "target not in _BATCH_DISPOSITION_TRANSITIONS[current]" not in source
