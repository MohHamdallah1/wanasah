import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  compactEditableMoney,
} from "@/pages/products/pricing/usePriceEditState";

const readSource = (relativePath: string): string =>
  readFileSync(
    new URL(relativePath, import.meta.url),
    "utf8",
  );

const compact = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("Products P9 tracking, barcode, lifecycle and pricing closure", () => {
  it("keeps tracking visible in plain language and backend-locked edits reachable", () => {
    const detailPanel = compact(
      readSource("../pages/products/detail/ProductDetailTabPanel.tsx"),
    );
    const actionMenu = compact(
      readSource("../pages/products/list/ProductRowActions.tsx"),
    );
    const editor = compact(
      readSource("../pages/products/tracking/ProductTrackingEditor.tsx"),
    );
    const mutation = compact(
      readSource("../pages/products/tracking/useProductTrackingMutations.ts"),
    );

    expect(detailPanel).toContain("products.tracking.lotModes.");
    expect(detailPanel).toContain("products.tracking.expiryModes.");
    expect(actionMenu).toContain("products.trackingEditor.action");
    expect(editor).toContain("products.trackingEditor.lockHint");
    expect(mutation).toContain("expected_version: trackingEdit.version");
    expect(mutation).toContain("PRODUCT_TRACKING_SCOPE_MISMATCH");
  });

  it("keeps barcode management reachable from Product row actions with durable deactivation", () => {
    const actionMenu = compact(
      readSource("../pages/products/list/ProductRowActions.tsx"),
    );
    const manager = compact(
      readSource("../pages/products/barcode/ProductBarcodeManager.tsx"),
    );

    expect(actionMenu).toContain("products.barcodeManager.action");
    expect(manager).toContain('"/catalog/variants/" + product.id + "/barcodes"');
    expect(manager).toContain('"/catalog/barcodes/" + item.id');
    expect(manager).toContain("expected_version: item.version");
    expect(manager).toContain("getOrCreateDurableCommand(");
    expect(manager).toContain("readDurableCommand<");
  });

  it("keeps lifecycle, sales hold and recall actions reachable through catalog authority", () => {
    const detailHero = compact(
      readSource("../pages/products/detail/ProductDetailHero.tsx"),
    );
    const actionMenu = compact(
      readSource("../pages/products/list/ProductRowActions.tsx"),
    );
    const manager = compact(
      readSource("../pages/products/lifecycle/ProductLifecycleManager.tsx"),
    );
    const actions = compact(
      readSource("../pages/inventory/catalog/CatalogLifecycleActions.tsx"),
    );

    expect(detailHero).toContain("products.details.holdModes.");
    expect(actionMenu).toContain("products.lifecycleManager.action");
    expect(manager).toContain("<CatalogLifecycleActions");
    expect(actions).toContain('"sales-hold"');
    expect(actions).toContain('"release-sales-hold"');
    expect(actions).toContain('"recall"');
    expect(actions).toContain('"close-recall"');
    expect(actions).toContain("getOrCreateDurableCommand(");
  });

  it("keeps pricing permission-aware and explains derived versus direct prices", () => {
    const capabilities = compact(
      readSource("../pages/products/deriveProductsCapabilities.ts"),
    );
    const drawer = compact(
      readSource("../pages/products/detail/ProductDetailDrawer.tsx"),
    );
    const detailPanel = compact(
      readSource("../pages/products/detail/ProductDetailTabPanel.tsx"),
    );
    const actionMenu = compact(
      readSource("../pages/products/list/ProductRowActions.tsx"),
    );
    const modal = compact(
      readSource("../pages/products/pricing/PriceEditModal.tsx"),
    );
    const create = compact(
      readSource("../pages/products/create/CreateProductCommerceSection.tsx"),
    );

    expect(capabilities).toContain('canAny("pricing.view")');
    expect(capabilities).toContain('canAny("pricing.manage")');
    expect(drawer).not.toContain("detailSections.pricing");
    expect(detailPanel).not.toContain("formatLocaleMoney");
    expect(actionMenu).toContain("canEditPrice && item.simple_compatible");
    expect(modal).toContain('"products.priceHelp"');
    expect(modal).toContain('"products.independentPrices"');
    expect(create).toContain('"products.derivedPrice"');
  });

  it("keeps raw six-decimal storage out of the ordinary price-edit presentation", () => {
    expect(
      compactEditableMoney(
        "13.500000",
      ),
    ).toBe("13.500");
    expect(
      compactEditableMoney(
        "0.270000",
      ),
    ).toBe("0.270");
    expect(
      compactEditableMoney(
        "12.345600",
      ),
    ).toBe("12.3456");

    const state = compact(
      readSource("../pages/products/pricing/usePriceEditState.ts"),
    );
    const modal = compact(
      readSource("../pages/products/pricing/PriceEditModal.tsx"),
    );
    const actions = compact(
      readSource("../pages/products/list/ProductRowActions.tsx"),
    );

    expect(state).toContain(
      "compactEditableMoney",
    );
    expect(state).toContain(
      "fraction.length > 3",
    );
    expect(state).toContain(
      'fraction.endsWith("0")',
    );
    expect(state).toContain(
      "fraction.padEnd( 3,",
    );
    expect(modal).toContain(
      "compactEditableMoney( derivedPackagePrice",
    );
    expect(modal).toContain(
      "compactEditableMoney( derivedUnitPrice",
    );
    expect(actions).toContain(
      '"products.details.actions"',
    );
    expect(actions).toContain(
      "<span>",
    );
  });

  it("preserves full durable commands for price and tracking ambiguous retries", () => {
    const priceMutation = compact(
      readSource("../pages/products/pricing/usePriceEditMutation.ts"),
    );
    const priceWorkflow = compact(
      readSource("../pages/products/pricing/usePriceEditWorkflow.ts"),
    );
    const trackingMutation = compact(
      readSource("../pages/products/tracking/useProductTrackingMutations.ts"),
    );
    const trackingWorkflow = compact(
      readSource("../pages/products/tracking/useProductTrackingWorkflow.ts"),
    );

    for (const source of [priceMutation, trackingMutation]) {
      expect(source).toContain("getOrCreateDurableCommand(");
      expect(source).toContain("completeDurableOperation(");
      expect(source).toContain("abandonDurableOperation(");
      expect(source).toContain("isAmbiguousRequestError(");
      expect(source).not.toContain("getOrCreateDurableRequestId(");
      expect(source).not.toContain("crypto.randomUUID()");
    }
    expect(priceWorkflow).toContain("readDurableCommand<unknown>(");
    expect(trackingWorkflow).toContain("readDurableCommand<unknown>(");
  });
});
