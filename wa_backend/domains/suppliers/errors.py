"""Stable Supplier errors; transport adapters decide how to present them."""
class SupplierError(Exception):
    def __init__(self, status, code, reason, context=None):
        super().__init__(reason)
        self.status_code = status
        self.code = code
        self.context = context or {}

    def as_detail(self):
        return {"code": self.code, "message": str(self), "context": self.context}


def fail(status, code, reason, **context):
    raise SupplierError(status, code, reason, context)
