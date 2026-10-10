"""Principal-aware HTTP authentication dependencies for the new identity model."""

from .dependencies import (
    get_current_backoffice_context,
    get_current_field_context,
    get_current_principal_context,
)

__all__ = [
    "get_current_backoffice_context",
    "get_current_field_context",
    "get_current_principal_context",
]
