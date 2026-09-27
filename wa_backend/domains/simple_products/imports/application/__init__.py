"""Application/use-case boundary for Product Import.

Application orchestration may depend on the import domain and existing owning
Product/Tracking/Pricing authorities. Infrastructure must be supplied through
explicit contracts/adapters rather than imported through package side effects.

No eager cross-layer imports are allowed here.
"""

__all__: tuple[str, ...] = ()
