"""HTTP transport boundary for Product Import.

This layer may depend on application/domain public contracts. It must not own
Product business rules or import infrastructure. Router exports will be added
when the Product Import endpoints are moved in their dedicated Phase 1 task.

No eager cross-layer imports are allowed here.
"""

__all__: tuple[str, ...] = ()
