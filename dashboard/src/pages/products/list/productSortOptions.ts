import type {
  ProductSortDirection,
  ProductSortField,
} from "@/pages/products/list/types";

export type ProductSortOption = {
  field: ProductSortField;
  direction: ProductSortDirection;
  key:
    | "activeFirst"
    | "retiringFirst"
    | "newest"
    | "oldest"
    | "nameAsc"
    | "nameDesc"
    | "familyAsc"
    | "familyDesc"
    | "skuAsc"
    | "skuDesc";
};

export const PRODUCT_SORT_OPTIONS: ProductSortOption[] = [
  {
    field: "lifecycle",
    direction: "asc",
    key: "activeFirst",
  },
  {
    field: "lifecycle",
    direction: "desc",
    key: "retiringFirst",
  },
  {
    field: "id",
    direction: "desc",
    key: "newest",
  },
  {
    field: "id",
    direction: "asc",
    key: "oldest",
  },
  {
    field: "name",
    direction: "asc",
    key: "nameAsc",
  },
  {
    field: "name",
    direction: "desc",
    key: "nameDesc",
  },
  {
    field: "family",
    direction: "asc",
    key: "familyAsc",
  },
  {
    field: "family",
    direction: "desc",
    key: "familyDesc",
  },
  {
    field: "sku",
    direction: "asc",
    key: "skuAsc",
  },
  {
    field: "sku",
    direction: "desc",
    key: "skuDesc",
  },
];

export function findProductSortOption(
  field: ProductSortField,
  direction: ProductSortDirection,
): ProductSortOption | undefined {
  return PRODUCT_SORT_OPTIONS.find(
    (option) =>
      option.field === field &&
      option.direction === direction,
  );
}
