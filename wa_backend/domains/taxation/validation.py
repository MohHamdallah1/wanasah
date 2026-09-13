from __future__ import annotations

from domains.taxation.core import TaxError
from domains.taxation.schemas import TaxComponentInput, TaxScopeInput


def validate_tax_configuration(
    *,
    components: list[TaxComponentInput],
    scopes: list[TaxScopeInput],
) -> None:
    if not components:
        raise TaxError(
            "TAX_COMPONENT_REQUIRED",
            "A tax rule-set version must contain at least one component.",
            status_code=422,
        )

    codes = [item.component_code for item in components]
    sequences = [item.sequence for item in components]
    if len(codes) != len(set(codes)):
        raise TaxError(
            "TAX_COMPONENT_CODE_DUPLICATE",
            "Tax component codes must be unique inside one version.",
            status_code=422,
        )
    if len(sequences) != len(set(sequences)):
        raise TaxError(
            "TAX_COMPONENT_SEQUENCE_DUPLICATE",
            "Tax component sequence values must be unique.",
            status_code=422,
        )
    if sorted(sequences) != list(range(1, len(components) + 1)):
        raise TaxError(
            "TAX_COMPONENT_SEQUENCE_INVALID",
            "Tax component sequence must be contiguous and start at 1.",
            status_code=422,
        )
    first = min(components, key=lambda item: item.sequence)
    if first.basis_mode != "TAXABLE_BASE":
        raise TaxError(
            "TAX_COMPONENT_BASIS_INVALID",
            "The first tax component must use TAXABLE_BASE.",
            status_code=422,
        )

    scope_keys = {
        (
            item.scope_type,
            item.jurisdiction_id,
            item.product_variant_id,
            item.customer_id,
            item.document_type_code,
        )
        for item in scopes
    }
    if len(scope_keys) != len(scopes):
        raise TaxError(
            "TAX_SCOPE_DUPLICATE",
            "Tax scope contains duplicate targets.",
            status_code=422,
        )
