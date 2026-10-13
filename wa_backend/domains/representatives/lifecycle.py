from __future__ import annotations


class RepresentativeLifecycleDecisionRequired(RuntimeError):
    pass


async def deactivate_representative(*args, **kwargs):
    raise RepresentativeLifecycleDecisionRequired(
        "Deactivation is blocked until active route/work-session safety semantics are frozen."
    )


async def reactivate_representative(*args, **kwargs):
    raise RepresentativeLifecycleDecisionRequired(
        "Reactivation is blocked until lifecycle/session semantics are frozen."
    )


__all__ = [
    "RepresentativeLifecycleDecisionRequired",
    "deactivate_representative",
    "reactivate_representative",
]
