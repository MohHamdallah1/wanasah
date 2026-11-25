import type { SimpleProduct } from "@/pages/products/contracts";

export const singleUnitProductDefaults = {
  units_per_package: 1,
  legacy_packs_per_carton: 1,
  base_uom_id: 1,
  base_uom_code: "EACH",
  package_uom_id: null,
  package_uom_code: null,
  currency_code: "JOD",
  package_price: null,
  unit_price: null,
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode: false,
  version: 3,
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  simple_compatible: true,
} as const satisfies Partial<SimpleProduct>;

export const packagedProductDefaults = {
  ...singleUnitProductDefaults,
  units_per_package: 50,
  legacy_packs_per_carton: 50,
  package_uom_id: 2,
  package_uom_code: "CARTON",
  lot_control_mode: "OPTIONAL",
} as const satisfies Partial<SimpleProduct>;

export const emptyProductStatusEvidence = {
  status_reason: null,
  batch_restrictions: null,
} as const satisfies Pick<SimpleProduct, "status_reason" | "batch_restrictions">;
