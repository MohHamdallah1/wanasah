"""Product Import domain-level errors."""


class ProductImportTerminalError(RuntimeError):
    """Deterministic import failure that must not be retried automatically."""
