from domains.product_tracking import (
    PLATFORM_DEFAULT_EXPIRY_CONTROL_MODE,
    PLATFORM_DEFAULT_LOT_CONTROL_MODE,
)


def test_platform_tracking_fallback_is_optional_for_general_smb_use() -> None:
    assert PLATFORM_DEFAULT_LOT_CONTROL_MODE == "OPTIONAL"
    assert PLATFORM_DEFAULT_EXPIRY_CONTROL_MODE == "OPTIONAL"