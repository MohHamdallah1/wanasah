export const IMPORT_MAPPING_FIELDS = [
  "name",
  "family",
  "package_uom",
  "units_per_package",
  "package_price",
  "unit_price",
  "unit_barcode",
  "package_barcode",
  "lot_control_mode",
  "expiry_control_mode",
] as const;

export type ImportMappingField =
  (typeof IMPORT_MAPPING_FIELDS)[number];

export const importMappingLabelKey = (
  field: ImportMappingField,
) => {
  const keys = {
    name: "products.fields.name",
    family: "products.fields.family",
    package_uom:
      "products.fields.packageUom",
    units_per_package:
      "products.fields.unitsPerPackage",
    package_price:
      "products.fields.packagePrice",
    unit_price:
      "products.fields.unitPrice",
    unit_barcode:
      "products.fields.unitBarcode",
    package_barcode:
      "products.fields.packageBarcode",
    lot_control_mode:
      "products.fields.lotControlMode",
    expiry_control_mode:
      "products.fields.expiryControlMode",
  } as const;

  return keys[field];
};
