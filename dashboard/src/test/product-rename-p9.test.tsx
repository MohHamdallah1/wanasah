import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  parseProductNameMutationResponse,
} from "@/pages/products/contracts";

const source = (relative: string) =>
  readFileSync(
    join(process.cwd(), relative),
    "utf8",
  );

describe("Products P9 published-name editing", () => {
  it("strictly parses the dedicated rename response", () => {
    expect(
      parseProductNameMutationResponse({
        product_variant_id: 42,
        name: "منتج جديد",
        version: 8,
        changed: true,
      }),
    ).toEqual({
      product_variant_id: 42,
      name: "منتج جديد",
      version: 8,
      changed: true,
    });

    expect(() =>
      parseProductNameMutationResponse({
        product_variant_id: 42,
        name: "",
        version: 8,
        changed: true,
      }),
    ).toThrow(
      "PRODUCT_NAME_MUTATION_RESPONSE_INVALID",
    );

    expect(() =>
      parseProductNameMutationResponse({
        product_variant_id: 42,
        name: "Valid",
        version: 0,
        changed: true,
      }),
    ).toThrow(
      "PRODUCT_NAME_MUTATION_RESPONSE_INVALID",
    );
  });

  it("keeps rename in a dedicated durable page-owned workflow", () => {
    const dialog = source(
      "src/pages/products/rename/ProductRenameDialog.tsx",
    );

    expect(dialog).toContain(
      '"catalog-product-name-update-v1"',
    );
    expect(dialog).toContain(
      "readDurableCommand<unknown>",
    );
    expect(dialog).toContain(
      "getOrCreateDurableCommand",
    );
    expect(dialog).toContain(
      "completeDurableOperation",
    );
    expect(dialog).toContain(
      "abandonDurableOperation",
    );
    expect(dialog).toContain(
      "/catalog/variants/",
    );
    expect(dialog).toContain(
      "/name",
    );
    expect(dialog).toContain(
      "expected_version:",
    );
    expect(dialog).toContain(
      "PRODUCT_NAME_MUTATION_SCOPE_MISMATCH",
    );
    expect(dialog).toContain(
      'queryKey: ["simple-products"]',
    );
    expect(dialog).not.toContain(
      "crypto.randomUUID",
    );
  });

  it("exposes rename through Product details only with catalog-manage capability", () => {
    const drawer = source(
      "src/pages/products/detail/ProductDetailDrawer.tsx",
    );
    const actionMenu = source(
      "src/pages/products/detail/ProductDetailActionsMenu.tsx",
    );
    const page = source(
      "src/pages/products/ProductsPage.tsx",
    );
    const detailActions = source(
      "src/pages/products/detail/createProductDetailActions.ts",
    );
    const detailWorkflow = source(
      "src/pages/products/detail/useProductDetailWorkflow.ts",
    );

    expect(drawer).toContain(
      "canRenameProduct: boolean",
    );
    expect(actionMenu).toContain(
      '"products.rename.action"',
    );
    expect(actionMenu).toContain(
      '["ACTIVE", "RETIRING"].includes',
    );
    expect(detailWorkflow).toContain(
      "canRenameProduct:",
    );
    expect(detailWorkflow).toContain(
      "canManageCatalog",
    );
    expect(page).toContain(
      "canManageCatalog",
    );
    expect(page).toContain(
      "<ProductRenameDialog",
    );
    expect(detailActions).toContain(
      "openRenameProduct(product)",
    );
  });

  it("keeps the generic structural editor locked after Draft", () => {
    const catalog = source(
      "../wa_backend/api/catalog.py",
    );
    const identity = source(
      "../wa_backend/domains/catalog_identity.py",
    );

    expect(catalog).toContain(
      'if row.lifecycle_status != "DRAFT":',
    );
    expect(catalog).toContain(
      '@router.patch("/variants/{variant_id}/name")',
    );
    expect(catalog).toContain(
      '"CATALOG_VARIANT_NAME_UPDATE_V1"',
    );
    expect(identity).toContain(
      '{"ACTIVE", "RETIRING"}',
    );
    expect(identity).toContain(
      '"ProductVariantRenamed"',
    );
    expect(identity).not.toContain(
      "lifecycle_revision +=",
    );
  });

  it("refreshes the Live Stock projection before commit", () => {
    const catalog = source(
      "../wa_backend/api/catalog.py",
    );

    const renameStart = catalog.indexOf(
      "async def rename_variant_name",
    );
    const renameEnd = catalog.indexOf(
      "async def _draft_variant",
      renameStart,
    );
    const renameBlock = catalog.slice(
      renameStart,
      renameEnd,
    );

    expect(renameBlock).toContain(
      "refresh_live_stock_variants",
    );
    expect(renameBlock).toContain(
      "complete_idempotent_operation",
    );
    expect(renameBlock).toContain(
      "await db.commit()",
    );
    expect(
      renameBlock.indexOf(
        "refresh_live_stock_variants",
      ),
    ).toBeLessThan(
      renameBlock.indexOf(
        "await db.commit()",
      ),
    );
  });
});
