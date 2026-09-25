import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import {
  parseProductFamilyReassignMutation,
} from "../pages/products/contracts";

const source = (
  relativePath: string,
) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  )
    .replace(/\s+/g, " ")
    .trim();

describe("Products P9 family reassignment", () => {
  it("parses the authoritative reassignment response including the new optimistic version", () => {
    expect(
      parseProductFamilyReassignMutation(
        {
          product_variant_id: 41,
          family_id: 9,
          family_name: "Snacks",
          version: 12,
          changed: true,
        },
      ),
    ).toEqual({
      product_variant_id: 41,
      family_id: 9,
      family_name: "Snacks",
      version: 12,
      changed: true,
    });
  });

  it("sends a durable family move with expected_version and family_id to the catalog authority", () => {
    const dialog = source(
      "../pages/products/family/ProductFamilyReassignDialog.tsx",
    );

    expect(dialog).toContain(
      '"catalog-product-family-reassign-v1"',
    );
    expect(dialog).toContain(
      "expected_version: expectedVersion ?? product.version",
    );
    expect(dialog).toContain(
      "family_id: pending?.payload .family_id ?? targetFamilyId ?? product.product_id",
    );
    expect(dialog).toContain(
      "/catalog/variants/",
    );
    expect(dialog).toContain(
      "/family",
    );
    expect(dialog).toContain(
      "request_id: command.requestId",
    );
    expect(dialog).toContain(
      "completeDurableOperation(",
    );
    expect(dialog).toContain(
      "abandonDurableOperation(",
    );
  });

  it("keeps backend lifecycle, history, and version authority visible instead of bypassing it", () => {
    const dialog = source(
      "../pages/products/family/ProductFamilyReassignDialog.tsx",
    );

    expect(dialog).toContain(
      '"PRODUCT_FAMILY_REASSIGN_HISTORY_LOCKED"',
    );
    expect(dialog).toContain(
      '"PRODUCT_FAMILY_REASSIGN_LIFECYCLE_BLOCKED"',
    );
    expect(dialog).toContain(
      '"VARIANT_VERSION_CONFLICT"',
    );
    expect(dialog).toContain(
      '"products.familyReassign.historyHint"',
    );
  });

  it("exposes family movement from Product Details only with catalog management authority", () => {
    const drawer = source(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );
    const workflow = source(
      "../pages/products/detail/useProductDetailWorkflow.ts",
    );
    const page = source(
      "../pages/products/ProductsPage.tsx",
    );

    expect(drawer).toContain(
      "canReassignFamily",
    );
    expect(drawer).toContain(
      '"products.familyReassign.action"',
    );
    expect(workflow).toContain(
      "canReassignFamily: canManageCatalog",
    );
    expect(page).toContain(
      "familyReassignWorkflow.openFamilyReassign",
    );
    expect(page).toContain(
      "<ProductFamilyReassignDialog",
    );
  });

  it("keeps SKU read-only for the published ACTIVE/RETIRING/ARCHIVED Products experience with a clear reason", () => {
    const drawer = source(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );
    const contracts = source(
      "../pages/products/contracts.ts",
    );

    expect(contracts).toContain(
      '| "ACTIVE"',
    );
    expect(contracts).toContain(
      '| "RETIRING"',
    );
    expect(contracts).toContain(
      '| "ARCHIVED"',
    );
    expect(contracts).not.toContain(
      '| "DRAFT"',
    );
    expect(drawer).toContain(
      "{product.sku}",
    );
    expect(drawer).toContain(
      '"products.details.skuLockedPublished"',
    );
    expect(drawer).not.toContain(
      "onEditSku",
    );
  });

  it("keeps optimistic version protection on every exposed Product identity mutation", () => {
    const rename = source(
      "../pages/products/rename/ProductRenameDialog.tsx",
    );
    const familyMove = source(
      "../pages/products/family/ProductFamilyReassignDialog.tsx",
    );
    const familyManager = source(
      "../pages/products/family/ProductFamiliesManager.tsx",
    );

    expect(rename).toContain(
      "expected_version: expectedVersion ?? product.version",
    );
    expect(familyMove).toContain(
      "expected_version: expectedVersion ?? product.version",
    );
    expect(familyManager).toContain(
      "expected_version: editingExpectedVersion ?? editingFamily.version",
    );
  });
});
