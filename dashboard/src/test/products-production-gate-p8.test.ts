import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  parseProductImportCommandResponse,
  parseSimpleProductCreateResponse,
  parseSimpleProductPriceMutationResponse,
} from "../pages/products/contracts";

const readSource = (relativePath: string): string =>
  readFileSync(
    new URL(relativePath, import.meta.url),
    "utf8",
  );

const compact = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("Products P8 production frontend gate", () => {
  it("strictly validates create and price mutation responses", () => {
    const created =
      parseSimpleProductCreateResponse({
        message: "Product created.",
        product_variant_id: 42,
        package_price: "13.500000",
        unit_price: "0.270000",
        lot_control_mode: "OPTIONAL",
        expiry_control_mode: "REQUIRED",
      });

    expect(created.product_variant_id).toBe(42);
    expect(created.unit_price).toBe("0.270000");

    const updated =
      parseSimpleProductPriceMutationResponse({
        message: "Prices updated.",
        product_variant_id: 42,
        package_price: null,
        unit_price: "0.300000",
      });
    expect(updated.package_price).toBeNull();

    expect(() =>
      parseSimpleProductCreateResponse({
        message: "Product created.",
        product_variant_id: 42,
        package_price: "13.500000",
        unit_price: 0.27,
        lot_control_mode: "OPTIONAL",
        expiry_control_mode: "REQUIRED",
      }),
    ).toThrow(
      "SIMPLE_PRODUCT_CREATE_RESPONSE_INVALID",
    );

    expect(() =>
      parseSimpleProductPriceMutationResponse({
        message: "Prices updated.",
        product_variant_id: 42,
        package_price: null,
        unit_price: null,
      }),
    ).toThrow(
      "SIMPLE_PRODUCT_PRICE_RESPONSE_INVALID",
    );
  });

  it("strictly validates import mapping/retry command responses", () => {
    const jobId =
      "123e4567-e89b-42d3-a456-426614174000";

    expect(
      parseProductImportCommandResponse({
        job_id: jobId,
        status: "VALIDATING",
        message: "Column mapping accepted.",
      }).job_id,
    ).toBe(jobId);

    expect(() =>
      parseProductImportCommandResponse({
        job_id: jobId,
        status: "UNKNOWN",
        message: "Invalid",
      }),
    ).toThrow(
      "PRODUCT_IMPORT_COMMAND_RESPONSE_INVALID",
    );
  });

  it("wires all remaining Products mutation boundaries through runtime parsers", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );
    const createMutation = compact(
      readSource(
        "../pages/products/create/useCreateProductMutation.ts",
      ),
    );

    expect(createMutation).toContain(
      "parseSimpleProductCreateResponse( await authFetch(",
    );
    expect(createMutation).toContain(
      "getOrCreateDurableRequestId(",
    );
    expect(createMutation).toContain(
      "completeDurableOperation(",
    );
    expect(createMutation).toContain(
      "abandonDurableOperation(",
    );
    expect(createMutation).toContain(
      "durableScope(",
    );
    expect(createMutation).toContain(
      '"product-create"',
    );
    expect(createMutation).not.toContain(
      "crypto.randomUUID()",
    );
    expect(page).toContain(
      "parseSimpleProductPriceMutationResponse( await authFetch(",
    );
    expect(page).toContain(
      "parseProductImportCommandResponse( await authFetch(",
    );
    expect(page).toContain(
      "result.product_variant_id !== priceEdit.id",
    );
    expect(page).toContain(
      "result.job_id !== importJobId",
    );
  });

  it("routes Products lifecycle management through the authoritative durable catalog workflow", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );
    const drawer = compact(
      readSource(
        "../pages/products/ProductDetailDrawer.tsx",
      ),
    );
    const manager = compact(
      readSource(
        "../pages/products/ProductLifecycleManager.tsx",
      ),
    );
    const actions = compact(
      readSource(
        "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
      ),
    );
    const catalogPanel = compact(
      readSource(
        "../pages/inventory/catalog/CatalogLifecyclePanel.tsx",
      ),
    );
    const backend = compact(
      readSource(
        "../../../wa_backend/api/simple_products.py",
      ),
    );

    expect(page).toContain(
      "<ProductLifecycleManager",
    );
    expect(page).toContain(
      "canManageLifecycle={ canManageLifecycle }",
    );
    expect(drawer).toContain(
      '"products.lifecycleManager.action"',
    );
    expect(manager).toContain(
      '"/catalog/variants/resolve"',
    );
    expect(manager).toContain(
      "parseCatalogPage(",
    );
    expect(actions).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(actions).toContain(
      "readDurableCommand<unknown>(",
    );
    expect(actions).toContain(
      '"catalog-lifecycle-command-v1"',
    );
    expect(actions).toContain(
      "isAmbiguousRequestError(",
    );
    expect(actions).not.toContain(
      "crypto.randomUUID()",
    );
    expect(catalogPanel).toContain(
      "<CatalogLifecycleActions",
    );
    expect(catalogPanel).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(catalogPanel).toContain(
      "readDurableCommand<unknown>(",
    );
    expect(catalogPanel).toContain(
      '"catalog-product-location-command-v1"',
    );
    expect(catalogPanel).toContain(
      "isAmbiguousRequestError(",
    );
    expect(catalogPanel).not.toContain(
      "crypto.randomUUID()",
    );
    expect(
      /[\u0600-\u06FF]/.test(
        readSource(
          "../pages/inventory/catalog/CatalogLifecyclePanel.tsx",
        ),
      ),
    ).toBe(false);
    expect(actions).not.toContain(
      "toast.success( result.message",
    );
    expect(backend).toContain(
      '"operational_hold": str( variant.operational_hold )',
    );
  });

  it("distinguishes package-UOM and import-poll failures from empty/loading states", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );
    const createModal = compact(
      readSource(
        "../pages/products/create/CreateProductModal.tsx",
      ),
    );
    const translations = readSource(
      "../i18n/resources.ts",
    );

    expect(page).toContain(
      "packageUomsLoading={ packageUomsQuery.isLoading }",
    );
    expect(createModal).toContain(
      "packageUomsLoading ? (",
    );
    expect(page).toContain(
      "packageUomsError={ packageUomsQuery.isError }",
    );
    expect(createModal).toContain(
      "packageUomsError ? (",
    );
    expect(page).toContain(
      "void packageUomsQuery.refetch()",
    );
    expect(page).toContain(
      "familyOptionsError={ familyOptionsQuery.isError }",
    );
    expect(createModal).toContain(
      "familyOptionsError ? (",
    );
    expect(page).toContain(
      "void familyOptionsQuery.refetch()",
    );
    expect(page).toContain(
      "importJobId && importPollError ? (",
    );
    expect(page).toContain(
      "setImportPollError( apiErrorMessage(",
    );
    expect(page).toContain(
      "setImportPollKey( (current) => current + 1",
    );

    expect(
      translations.match(
        /packageUomsLoad:/g,
      ),
    ).toHaveLength(2);
    expect(
      translations.match(
        /importStatusLoad:/g,
      ),
    ).toHaveLength(2);
  });
});
