"""Infrastructure adapters for Product Import.

This layer owns technical adapters such as parsing, persistence, queues and
template generation. It may implement application/domain contracts, but it
must never become Product/Tracking/Pricing business authority.

No eager cross-layer imports are allowed here.
"""

__all__: tuple[str, ...] = ()
