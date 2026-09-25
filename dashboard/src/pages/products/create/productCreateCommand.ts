import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";
import type {
  ProductDraft,
  ProductFamilyMode,
} from "@/pages/products/create/types";

export type ProductCreateCommandPayload = {
  name: string;
  family_mode: ProductFamilyMode;
  family_id: number | null;
  family_name: string | null;
  family_label: string;
  package_uom_code: string | null;
  units_per_package: number;
  package_price: string | null;
  unit_price: string | null;
  unit_barcode: string | null;
  package_barcode: string | null;
  lot_control_mode: ProductTrackingMode;
  expiry_control_mode: ProductTrackingMode;
};

const TRACKING_MODES =
  new Set<ProductTrackingMode>([
    "NONE",
    "OPTIONAL",
    "REQUIRED",
  ]);

const hasExactKeys = (
  row: Record<string, unknown>,
) => {
  const expected = [
    "expiry_control_mode",
    "family_id",
    "family_label",
    "family_mode",
    "family_name",
    "lot_control_mode",
    "name",
    "package_barcode",
    "package_price",
    "package_uom_code",
    "unit_barcode",
    "unit_price",
    "units_per_package",
  ].sort();
  return JSON.stringify(
    Object.keys(row).sort(),
  ) === JSON.stringify(expected);
};

const optionalTrimmed = (
  value: unknown,
  maximum: number,
): value is string | null =>
  value === null ||
  (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= maximum
  );

export const isProductCreateCommandPayload = (
  value: unknown,
): value is ProductCreateCommandPayload => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row =
    value as Record<string, unknown>;
  if (!hasExactKeys(row)) {
    return false;
  }

  const familyMode =
    row.family_mode;
  const familyId =
    row.family_id;
  const familyName =
    row.family_name;
  const familyLabel =
    row.family_label;
  const packageCode =
    row.package_uom_code;
  const units =
    row.units_per_package;
  const packagePrice =
    row.package_price;
  const unitPrice =
    row.unit_price;
  const unitBarcode =
    row.unit_barcode;
  const packageBarcode =
    row.package_barcode;
  const lot =
    row.lot_control_mode;
  const expiry =
    row.expiry_control_mode;

  if (
    typeof row.name !== "string" ||
    !row.name.trim() ||
    row.name.length > 200 ||
    ![
      "none",
      "existing",
      "new",
    ].includes(String(familyMode)) ||
    typeof familyLabel !== "string" ||
    familyLabel.length > 150 ||
    !optionalTrimmed(
      familyName,
      150,
    ) ||
    (
      familyId !== null &&
      (
        typeof familyId !== "number" ||
        !Number.isSafeInteger(familyId) ||
        familyId <= 0
      )
    ) ||
    !optionalTrimmed(
      packageCode,
      30,
    ) ||
    typeof units !== "number" ||
    !Number.isSafeInteger(units) ||
    units <= 0 ||
    units > 1_000_000 ||
    !optionalTrimmed(
      packagePrice,
      128,
    ) ||
    !optionalTrimmed(
      unitPrice,
      128,
    ) ||
    !optionalTrimmed(
      unitBarcode,
      128,
    ) ||
    !optionalTrimmed(
      packageBarcode,
      128,
    ) ||
    !TRACKING_MODES.has(
      lot as ProductTrackingMode,
    ) ||
    !TRACKING_MODES.has(
      expiry as ProductTrackingMode,
    )
  ) {
    return false;
  }

  if (
    familyMode === "none" &&
    (
      familyId !== null ||
      familyName !== null ||
      familyLabel !== ""
    )
  ) {
    return false;
  }
  if (
    familyMode === "existing" &&
    (
      familyId === null ||
      familyName !== null ||
      !familyLabel.trim()
    )
  ) {
    return false;
  }
  if (
    familyMode === "new" &&
    (
      familyId !== null ||
      familyName === null ||
      !familyLabel.trim() ||
      familyName.trim() !==
        familyLabel.trim()
    )
  ) {
    return false;
  }

  if (packageCode === null) {
    return (
      units === 1 &&
      packagePrice === null &&
      packageBarcode === null &&
      unitPrice !== null
    );
  }

  return (
    units >= 2 &&
    (
      packagePrice !== null ||
      unitPrice !== null
    )
  );
};

export const productCreateRequestBody = (
  payload: ProductCreateCommandPayload,
) => ({
  name: payload.name,
  family_id: payload.family_id,
  family_name: payload.family_name,
  package_uom_code:
    payload.package_uom_code,
  units_per_package:
    payload.units_per_package,
  package_price:
    payload.package_price,
  unit_price:
    payload.unit_price,
  unit_barcode:
    payload.unit_barcode,
  package_barcode:
    payload.package_barcode,
  lot_control_mode:
    payload.lot_control_mode,
  expiry_control_mode:
    payload.expiry_control_mode,
});

export const productDraftFromCreateCommand = (
  payload: ProductCreateCommandPayload,
): ProductDraft => ({
  name: payload.name,
  family_mode:
    payload.family_mode,
  family_id:
    payload.family_id,
  family:
    payload.family_label,
  has_package:
    payload.package_uom_code !== null,
  package_uom_code:
    payload.package_uom_code ??
    "CARTON",
  units_per_package:
    String(
      payload.units_per_package,
    ),
  package_price:
    payload.package_price ?? "",
  unit_price:
    payload.unit_price ?? "",
  unit_barcode:
    payload.unit_barcode ?? "",
  package_barcode:
    payload.package_barcode ?? "",
  lot_control_mode:
    payload.lot_control_mode,
  expiry_control_mode:
    payload.expiry_control_mode,
});
