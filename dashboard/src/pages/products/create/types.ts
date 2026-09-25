import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";

export type CreateFieldError = {
  field:
    | "name"
    | "family"
    | "units"
    | "packagePrice"
    | "unitPrice";
  message: string;
};

export type ProductFamilyMode =
  | "none"
  | "existing"
  | "new";

export type ProductDraft = {
  name: string;
  family_mode: ProductFamilyMode;
  family_id: number | null;
  family: string;
  has_package: boolean;
  package_uom_code: string;
  units_per_package: string;
  package_price: string;
  unit_price: string;
  unit_barcode: string;
  package_barcode: string;
  lot_control_mode: ProductTrackingMode | null;
  expiry_control_mode: ProductTrackingMode | null;
};
