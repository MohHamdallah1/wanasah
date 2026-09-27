"""Product Import capability package.

Dependency direction is intentionally one-way:

    api -> application -> domain
    infrastructure -> application/domain

The package root performs no eager imports. Consumers must import from the
owning layer public __init__ surface. This keeps package initialization
side-effect free and prevents circular imports as the capability grows.
"""

__all__ = (
    "api",
    "application",
    "domain",
    "infrastructure",
)
