"""Stable, transport-neutral purchase-reference errors."""


class PurchaseReferenceError(ValueError):
    def __init__(self, code, message, *, status_code=409, context=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = dict(context or {})

    def detail(self):
        return {"code": self.code, "message": self.message, "context": self.context}
