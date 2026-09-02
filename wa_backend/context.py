import contextvars

# الذاكرة السياقية (Context Variable) لحفظ هوية الشركة خلال الـ Request
tenant_context = contextvars.ContextVar("tenant_context", default=None)