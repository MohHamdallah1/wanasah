export type ProductLifecycleFilter =
  | ""
  | "ACTIVE"
  | "RETIRING";

export type ProductTrackingTypeFilter =
  | ""
  | "NONE"
  | "LOT"
  | "EXPIRY"
  | "LOT_EXPIRY";

export type ProductBooleanFilter =
  | ""
  | "true"
  | "false";

export type ProductSortField =
  | "id"
  | "name"
  | "family"
  | "sku"
  | "lifecycle";

export type ProductSortDirection =
  | "asc"
  | "desc";
