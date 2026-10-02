"""Barcode identity commands with history-preserving primary replacement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ProductBarcode,
    ProductUomConversion,
    ProductVariant,
)

_DIGITS_RE = re.compile(r"^\d+$")


class BarcodeIdentityError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = dict(context or {})


@dataclass(frozen=True)
class PrimaryBarcodeReplacementResult:
    barcode: ProductBarcode
    previous_barcode: str | None
    previous_barcode_id: int | None
    changed: bool


def normalize_barcode_value(value: object) -> str:
    if not isinstance(value, str):
        raise BarcodeIdentityError(
            "BARCODE_VALUE_INVALID",
            "Barcode must be text.",
            status_code=422,
        )
    clean = value.strip()
    if not clean or "\x00" in clean or len(clean) > 128:
        raise BarcodeIdentityError(
            "BARCODE_VALUE_INVALID",
            "Barcode is invalid.",
            status_code=422,
        )
    return clean


def _valid_gtin(value: str) -> bool:
    if (
        not _DIGITS_RE.fullmatch(value)
        or len(value) not in {8, 12, 13, 14}
    ):
        return False
    digits = [int(char) for char in value]
    expected = (
        10
        - sum(
            digit
            * (
                3
                if (
                    len(digits)
                    - 1
                    - index
                )
                % 2
                == 0
                else 1
            )
            for index, digit in enumerate(
                digits[:-1]
            )
        )
        % 10
    ) % 10
    return digits[-1] == expected


def infer_barcode_type(value: str) -> str:
    clean = normalize_barcode_value(value)
    if _valid_gtin(clean):
        return {
            8: "EAN8",
            12: "UPC_A",
            13: "EAN13",
            14: "GTIN14",
        }[len(clean)]
    return "INTERNAL"


async def replace_primary_barcode(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    uom_id: int,
    barcode: str,
    expected_current_id: int | None,
    expected_current_version: int | None,
) -> PrimaryBarcodeReplacementResult:
    clean = normalize_barcode_value(
        barcode
    )

    variant = await db.scalar(
        select(ProductVariant)
        .where(
            ProductVariant.company_id
            == int(company_id),
            ProductVariant.id
            == int(product_variant_id),
        )
        .with_for_update()
    )
    if variant is None:
        raise BarcodeIdentityError(
            "VARIANT_NOT_FOUND",
            "Product was not found.",
            status_code=404,
        )

    allowed_uom_ids = {
        int(variant.base_uom_id),
    }
    conversion_rows = (
        await db.execute(
            select(
                ProductUomConversion.from_uom_id,
                ProductUomConversion.to_uom_id,
            ).where(
                ProductUomConversion.company_id
                == int(company_id),
                ProductUomConversion.product_variant_id
                == int(product_variant_id),
            )
        )
    ).all()
    for (
        from_uom_id,
        to_uom_id,
    ) in conversion_rows:
        allowed_uom_ids.add(
            int(from_uom_id)
        )
        allowed_uom_ids.add(
            int(to_uom_id)
        )

    if int(uom_id) not in allowed_uom_ids:
        raise BarcodeIdentityError(
            "BARCODE_UOM_NOT_IN_PRODUCT",
            "Barcode unit is not part of this product.",
            status_code=422,
            context={"uom_id": int(uom_id)},
        )

    current = await db.scalar(
        select(ProductBarcode)
        .where(
            ProductBarcode.company_id
            == int(company_id),
            ProductBarcode.product_variant_id
            == int(product_variant_id),
            ProductBarcode.uom_id
            == int(uom_id),
            ProductBarcode.is_active.is_(
                True
            ),
            ProductBarcode.is_primary.is_(
                True
            ),
        )
        .with_for_update()
    )

    if (
        expected_current_id is None
    ) != (
        expected_current_version is None
    ):
        raise BarcodeIdentityError(
            "BARCODE_EXPECTATION_INVALID",
            "Current barcode identity is incomplete.",
            status_code=422,
        )

    if expected_current_id is None:
        if current is not None:
            raise BarcodeIdentityError(
                "BARCODE_VERSION_CONFLICT",
                "Barcode changed. Refresh and retry.",
                context={
                    "current_barcode_id": int(
                        current.id
                    ),
                    "current_version": int(
                        current.version
                    ),
                },
            )
    else:
        if (
            current is None
            or int(current.id)
            != int(expected_current_id)
            or int(current.version)
            != int(
                expected_current_version
            )
        ):
            raise BarcodeIdentityError(
                "BARCODE_VERSION_CONFLICT",
                "Barcode changed. Refresh and retry.",
                context={
                    "current_barcode_id": (
                        int(current.id)
                        if current is not None
                        else None
                    ),
                    "current_version": (
                        int(current.version)
                        if current is not None
                        else None
                    ),
                },
            )

    if (
        current is not None
        and str(current.barcode)
        == clean
    ):
        return PrimaryBarcodeReplacementResult(
            barcode=current,
            previous_barcode=str(
                current.barcode
            ),
            previous_barcode_id=int(
                current.id
            ),
            changed=False,
        )

    existing_active = await db.scalar(
        select(ProductBarcode)
        .where(
            ProductBarcode.company_id
            == int(company_id),
            ProductBarcode.barcode
            == clean,
            ProductBarcode.is_active.is_(
                True
            ),
        )
        .with_for_update()
    )
    if (
        existing_active is not None
        and (
            int(
                existing_active.product_variant_id
            )
            != int(product_variant_id)
            or int(existing_active.uom_id)
            != int(uom_id)
        )
    ):
        raise BarcodeIdentityError(
            "BARCODE_CONFLICT",
            "Barcode is already active for another product or unit.",
            status_code=409,
        )

    previous_barcode = (
        str(current.barcode)
        if current is not None
        else None
    )
    previous_barcode_id = (
        int(current.id)
        if current is not None
        else None
    )

    now = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    if current is not None:
        current.is_primary = False
        current.is_active = False
        current.valid_to = max(
            now,
            current.valid_from
            + timedelta(microseconds=1),
        )
        current.version = (
            int(current.version) + 1
        )
        await db.flush()

    if existing_active is not None:
        existing_active.is_primary = True
        existing_active.valid_to = None
        existing_active.version = (
            int(existing_active.version)
            + 1
        )
        await db.flush()
        replacement = existing_active
    else:
        replacement = ProductBarcode(
            company_id=int(company_id),
            product_variant_id=int(
                product_variant_id
            ),
            uom_id=int(uom_id),
            barcode=clean,
            barcode_type=infer_barcode_type(
                clean
            ),
            is_primary=True,
            valid_from=now,
            valid_to=None,
            is_active=True,
        )
        db.add(replacement)
        await db.flush()

    return PrimaryBarcodeReplacementResult(
        barcode=replacement,
        previous_barcode=previous_barcode,
        previous_barcode_id=previous_barcode_id,
        changed=True,
    )
