export type CursorPage<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
};

export type ApprovalPolicy = {
  maker_checker_enabled: boolean;
};

export type LifecycleStatus =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "PUBLISHED"
  | "SUPERSEDED"
  | "CANCELLED";

export type OfferDefinition = {
  id: number;
  code: string;
  name: string;
  description: string | null;
  version: number;
  created_by: number;
  created_at: string | null;
  updated_at: string | null;
};

export type OfferScope = {
  scope_type: "PRODUCT_VARIANT" | "CUSTOMER" | "BRANCH" | "CHANNEL";
  product_variant_id: number | null;
  uom_id: number | null;
  customer_id: number | null;
  branch_id: number | null;
  channel_code: string | null;
};

export type OfferProduct = {
  role: "QUALIFYING" | "REWARD" | "BUNDLE_COMPONENT";
  product_variant_id: number;
  uom_id: number;
  quantity_per_application: string | null;
};

export type OfferVersion = {
  id: number;
  offer_definition_id: number;
  revision: number;
  definition_version: number;
  status: LifecycleStatus;
  offer_type:
    | "PERCENTAGE_DISCOUNT"
    | "FIXED_DISCOUNT"
    | "BUY_X_GET_Y"
    | "FREE_GOODS"
    | "QUANTITY_TIERS"
    | "BUNDLE";
  payload: Record<string, unknown>;
  currency_code: string | null;
  priority: number;
  stacking_mode: "EXCLUSIVE" | "STACKABLE";
  effective_from: string;
  effective_to: string | null;
  request_id: string;
  created_by: number;
  approved_by: number | null;
  approved_at: string | null;
  published_at: string | null;
  cancelled_by: number | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  version: number;
  scopes: OfferScope[];
  products: OfferProduct[];
};

export type TaxJurisdiction = {
  id: number;
  code: string;
  name: string;
  jurisdiction_type: "COUNTRY" | "SUBDIVISION" | "LOCALITY" | "CUSTOM";
  country_code: string;
  subdivision_code: string | null;
  locality_code: string | null;
  parent_jurisdiction_id: number | null;
  is_active: boolean;
  version: number;
};

export type TaxRuleSet = {
  id: number;
  code: string;
  name: string;
  description: string | null;
  version: number;
  created_by: number;
  created_at: string | null;
  updated_at: string | null;
};

export type TaxComponent = {
  component_code: string;
  name: string;
  sequence: number;
  rate: string;
  basis_mode: "TAXABLE_BASE" | "TAXABLE_BASE_PLUS_PRIOR_TAX";
  reporting_code: string | null;
};

export type TaxScope = {
  scope_type: "JURISDICTION" | "PRODUCT_VARIANT" | "CUSTOMER" | "DOCUMENT_TYPE";
  jurisdiction_id: number | null;
  product_variant_id: number | null;
  customer_id: number | null;
  document_type_code: string | null;
};

export type TaxVersion = {
  id: number;
  tax_rule_set_id: number;
  revision: number;
  definition_version: number;
  status: LifecycleStatus;
  priority: number;
  price_mode: "EXCLUSIVE" | "INCLUSIVE";
  effective_from: string;
  effective_to: string | null;
  request_id: string;
  created_by: number;
  approved_by: number | null;
  approved_at: string | null;
  published_at: string | null;
  cancelled_by: number | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  version: number;
  components: TaxComponent[];
  scopes: TaxScope[];
};

export type OfferPreview = {
  calculated_at: string;
  currency_code: string;
  price_publication_revision_ceiling: number;
  assignment_revision_ceiling: number;
  offer_revision_ceiling: number;
  gross_amount: string;
  discount_amount: string;
  net_amount: string;
  lines: Array<{
    line_id: number;
    product_variant_id: number;
    base_uom_id: number;
    canonical_quantity: string;
    gross_amount: string;
    net_amount: string;
    price_components: Array<{
      uom_id: number;
      quantity: string;
      base_quantity: string;
      unit_price: string;
      price_entry_id: number;
      gross_amount: string;
    }>;
  }>;
  adjustments: Array<{
    sequence: number;
    offer_version_id: number;
    offer_definition_id: number;
    offer_revision: number;
    offer_type: string;
    line_id: number | null;
    product_variant_id: number | null;
    uom_id: number | null;
    basis_amount: string;
    discount_amount: string;
  }>;
  free_goods: Array<{
    sequence: number;
    offer_version_id: number;
    offer_definition_id: number;
    offer_revision: number;
    offer_type: string;
    product_variant_id: number;
    uom_id: number;
    quantity: string;
  }>;
  applied_offers: Array<{
    sequence: number;
    offer_version_id: number;
    offer_definition_id: number;
    offer_revision: number;
    offer_type: string;
    priority: number;
    stacking_mode: string;
    application_count: number;
    discount_amount: string;
    reward_value: string;
    benefit_amount: string;
    metadata: Record<string, unknown>;
  }>;
};

export type TaxPreview = {
  calculated_at: string;
  jurisdiction_id: number;
  customer_id: number | null;
  document_type_code: string;
  tax_revision_ceiling: number;
  lines: Array<{
    line_id: number;
    product_variant_id: number;
    input_amount: string;
    taxable_base: string;
    tax_amount: string;
    total_amount: string;
    resolution: {
      tax_rule_set_id: number;
      tax_rule_set_version_id: number;
      tax_revision: number;
      definition_version: number;
      priority: number;
      price_mode: string;
      scope_types: string[];
      matched_jurisdiction_id: number | null;
      jurisdiction_distance: number | null;
      resolved_at: string;
    };
    components: Array<{
      tax_component_id: number;
      component_code: string;
      name: string;
      sequence: number;
      rate: string;
      basis_mode: string;
      reporting_code: string | null;
      basis_amount: string;
      tax_amount: string;
    }>;
  }>;
  totals: {
    taxable_base: string;
    tax_amount: string;
    total_amount: string;
  };
};

export type CatalogUom = { id: number; code: string; name: string };

export type CatalogVariant = {
  id: number;
  product_id: number;
  sku: string;
  name: string;
  base_uom: CatalogUom;
  quantity_scale: number;
  quantity_step: string;
  lifecycle_status: string;
  operational_hold: string;
  version: number;
};

export type OfferCatalogVariant = CatalogVariant & {
  uoms: CatalogUom[];
};

export type OfferType = OfferVersion["offer_type"];
export type OfferScopeType = OfferScope["scope_type"];
export type OfferProductRole = OfferProduct["role"];
export type TaxScopeType = TaxScope["scope_type"];
