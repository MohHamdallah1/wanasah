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
        "../pages/products/ProductsPage.tsx",
      ),
    );
    const createMutation = compact(
      readSource(
        "../pages/products/create/useCreateProductMutation.ts",
      ),
    );
    const createWorkflow = compact(
      readSource(
        "../pages/products/create/useCreateProductWorkflow.ts",
      ),
    );
    const priceMutation = compact(
      readSource(
        "../pages/products/pricing/usePriceEditMutation.ts",
      ),
    );
    const priceWorkflow = compact(
      readSource(
        "../pages/products/pricing/usePriceEditWorkflow.ts",
      ),
    );
    const trackingMutations = compact(
      readSource(
        "../pages/products/tracking/useProductTrackingMutations.ts",
      ),
    );
    const trackingWorkflow = compact(
      readSource(
        "../pages/products/tracking/useProductTrackingWorkflow.ts",
      ),
    );
    const importUpload = compact(
      readSource(
        "../pages/products/import/useImportProductUpload.ts",
      ),
    );
    const importCommands = compact(
      readSource(
        "../pages/products/import/useImportProductCommands.ts",
      ),
    );
    const productScope = compact(
      readSource(
        "../pages/products/productDurableScope.ts",
      ),
    );

    expect(productScope).toContain(
      "durableScope(",
    );
    expect(productScope).toContain(
      '"IDENTITY_NOT_READY"',
    );

    expect(createMutation).toContain(
      "parseSimpleProductCreateResponse( await authFetch(",
    );
    expect(createMutation).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(createMutation).toContain(
      "completeDurableOperation(",
    );
    expect(createMutation).toContain(
      "isAmbiguousRequestError(",
    );
    expect(createWorkflow).toContain(
      "readDurableCommand<unknown>(",
    );
    expect(createMutation).toContain(
      "abandonDurableOperation(",
    );
    expect(createMutation).toContain(
      "productDurableScope(",
    );
    expect(createMutation).toContain(
      '"product-create"',
    );
    expect(createMutation).not.toContain(
      "crypto.randomUUID()",
    );
    expect(priceMutation).toContain(
      "parseSimpleProductPriceMutationResponse( await authFetch(",
    );
    expect(priceMutation).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(priceMutation).toContain(
      "completeDurableOperation(",
    );
    expect(priceMutation).toContain(
      "abandonDurableOperation(",
    );
    expect(priceMutation).toContain(
      "isAmbiguousRequestError(",
    );
    expect(priceWorkflow).toContain(
      "readDurableCommand<unknown>(",
    );
    expect(priceMutation).toContain(
      '"product-price"',
    );
    expect(priceMutation).toContain(
      "productDurableScope(",
    );
    expect(priceMutation).not.toContain(
      "crypto.randomUUID()",
    );
    expect(trackingMutations).toContain(
      "parseProductTrackingDefaults( await authFetch(",
    );
    expect(trackingMutations).toContain(
      "parseProductTrackingMutation( await authFetch(",
    );
    expect(trackingMutations).toContain(
      '"product-tracking-defaults"',
    );
    expect(trackingMutations).toContain(
      '"product-tracking"',
    );
    expect(trackingMutations).toContain(
      "expected_version: trackingEdit.version",
    );
    expect(trackingMutations).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(trackingMutations).toContain(
      "abandonDurableOperation(",
    );
    expect(trackingMutations).toContain(
      "isAmbiguousRequestError(",
    );
    expect(trackingWorkflow).toContain(
      "readDurableCommand<unknown>(",
    );
    expect(trackingMutations).toContain(
      "productDurableScope(",
    );
    expect(trackingMutations).toContain(
      "completeDurableOperation(",
    );
    expect(trackingMutations).not.toContain(
      "crypto.randomUUID()",
    );
    expect(importUpload).toContain(
      "parseProductImportAccepted( await authFetch(",
    );
    expect(importUpload).toContain(
      "fileFingerprint(",
    );
    expect(importUpload).toContain(
      "getOrCreateDurableRequestId(",
    );
    expect(importUpload).toContain(
      "completeDurableOperation(",
    );
    expect(importUpload).toContain(
      "productDurableScope(",
    );
    expect(importUpload).not.toContain(
      "crypto.randomUUID()",
    );
    expect(importCommands).toContain(
      "parseProductImportCommandResponse( await authFetch(",
    );
    expect(priceMutation).toContain(
      "result.product_variant_id !== priceEdit.id",
    );
    expect(importCommands).toContain(
      "result.job_id !== importJobId",
    );
  });

  it("routes Products lifecycle management through the authoritative durable catalog workflow", () => {
    const page = compact(
      readSource(
        "../pages/products/ProductsPage.tsx",
      ),
    );
    const drawer = compact(
      readSource(
        "../pages/products/detail/ProductDetailDrawer.tsx",
      ),
    );
    const detailActionMenu = compact(
      readSource(
        "../pages/products/detail/ProductDetailActionsMenu.tsx",
      ),
    );
    const detailWorkflow = compact(
      readSource(
        "../pages/products/detail/useProductDetailWorkflow.ts",
      ),
    );
    const manager = compact(
      readSource(
        "../pages/products/lifecycle/ProductLifecycleManager.tsx",
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
    expect(detailWorkflow).toContain(
      "canManageLifecycle",
    );
    expect(detailActionMenu).toContain(
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

  it("keeps import lifecycle cleanup feature-owned and deterministic", () => {
    const page = compact(
      readSource(
        "../pages/products/ProductsPage.tsx",
      ),
    );
    const catalogTools = compact(
      readSource(
        "../pages/products/header/ProductsCatalogToolsMenu.tsx",
      ),
    );
    const fileActions = compact(
      readSource(
        "../pages/products/import/createImportFileActions.ts",
      ),
    );
    const importWorkflow = compact(
      readSource(
        "../pages/products/import/useImportProductWorkflow.ts",
      ),
    );

    expect(fileActions).toContain(
      'lower.endsWith( ".csv" )',
    );
    expect(fileActions).toContain(
      'lower.endsWith( ".xlsx" )',
    );
    expect(fileActions).toContain(
      "if (!importing)",
    );
    expect(fileActions).toContain(
      "sessionStorage.removeItem( importSessionKey )",
    );
    expect(fileActions).toContain(
      'fileRef.current.value = ""',
    );
    expect(fileActions).toContain(
      "setImportJobId(null)",
    );
    expect(fileActions).toContain(
      "setImportStatus(null)",
    );
    expect(fileActions).toContain(
      "setMapping({})",
    );
    expect(page).toContain(
      "onOpenImport={ importWorkflow.openImport }",
    );
    expect(catalogTools).toContain(
      "onSelect={onOpenImport}",
    );
    expect(importWorkflow).toContain(
      "onClose: closeImport",
    );
    expect(importWorkflow).toContain(
      "onCompletedClose: completeImport",
    );
  });

  it("distinguishes package-UOM and import-poll failures from empty/loading states", () => {
    const page = compact(
      readSource(
        "../pages/products/ProductsPage.tsx",
      ),
    );
    const createIdentity = compact(
      readSource(
        "../pages/products/create/CreateProductIdentitySection.tsx",
      ),
    );
    const createCommerce = compact(
      readSource(
        "../pages/products/create/CreateProductCommerceSection.tsx",
      ),
    );
    const createWorkflow = compact(
      readSource(
        "../pages/products/create/useCreateProductWorkflow.ts",
      ),
    );
    const importModal = compact(
      readSource(
        "../pages/products/import/ImportProductModal.tsx",
      ),
    );
    const importWorkflow = compact(
      readSource(
        "../pages/products/import/useImportProductWorkflow.ts",
      ),
    );
    const importPolling = compact(
      readSource(
        "../pages/products/import/useImportProductPolling.ts",
      ),
    );
    const translations = readSource(
      "../i18n/resources.ts",
    );

    expect(createWorkflow).toContain(
      "packageUomsLoading: packageUomsQuery.isLoading",
    );
    expect(createCommerce).toContain(
      "packageUomsLoading ? (",
    );
    expect(createWorkflow).toContain(
      "packageUomsError: packageUomsQuery.isError",
    );
    expect(createCommerce).toContain(
      "packageUomsError ? (",
    );
    expect(createWorkflow).toContain(
      "void packageUomsQuery.refetch()",
    );
    expect(createWorkflow).toContain(
      "familyOptionsError: familyOptionsQuery.isError",
    );
    expect(createIdentity).toContain(
      "familyOptionsError ? (",
    );
    expect(createWorkflow).toContain(
      "void familyOptionsQuery.refetch()",
    );
    expect(importWorkflow).toContain(
      "pollError: importPollError",
    );
    expect(importModal).toContain(
      "jobId && pollError ? (",
    );
    expect(importPolling).toContain(
      "setImportPollError( apiErrorMessage(",
    );
    expect(importPolling).toContain(
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
