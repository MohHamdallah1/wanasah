import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products P9.4 lifecycle workspace", () => {
  it("keeps lifecycle command authority in the shared Catalog action component", () => {
    const manager = read(
      "../pages/products/lifecycle/ProductLifecycleManager.tsx",
    );
    const catalogActions = read(
      "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
    );

    expect(manager).toContain(
      "<CatalogLifecycleActions",
    );
    expect(manager).not.toContain(
      "getOrCreateDurableCommand(",
    );
    expect(manager).not.toContain(
      "/archive-preflight",
    );
    expect(manager).not.toContain(
      "/sales-hold",
    );

    for (const command of [
      '"retire"',
      '"restore"',
      '"archive"',
      '"sales-hold"',
      '"release-sales-hold"',
      '"recall"',
      '"close-recall"',
    ]) {
      expect(catalogActions).toContain(
        command,
      );
    }
  });

  it("shows current lifecycle hold and version before actions", () => {
    const manager = read(
      "../pages/products/lifecycle/ProductLifecycleManager.tsx",
    );
    const rail = read(
      "../pages/products/lifecycle/ProductLifecycleStatusRail.tsx",
    );

    expect(manager).toContain(
      "<ProductLifecycleStatusRail",
    );
    expect(rail).toContain(
      '"products.details.lifecycle"',
    );
    expect(rail).toContain(
      '"products.details.operationalHold"',
    );
    expect(rail).toContain(
      "products.details.lifecycleModes.",
    );
    expect(rail).toContain(
      "products.details.holdModes.",
    );
    expect(rail).toContain(
      "v{variant.version}",
    );
  });

  it("keeps lifecycle status understandable without depending on color alone", () => {
    const rail = read(
      "../pages/products/lifecycle/ProductLifecycleStatusRail.tsx",
    );

    expect(rail).toContain(
      "variant.lifecycle_status",
    );
    expect(rail).toContain(
      "variant.operational_hold",
    );
    expect(rail).toContain(
      "bg-emerald-50",
    );
    expect(rail).toContain(
      "bg-rose-50",
    );
  });

  it("keeps load failure local and retryable inside the Product lifecycle modal", () => {
    const manager = read(
      "../pages/products/lifecycle/ProductLifecycleManager.tsx",
    );

    expect(manager).toContain(
      'role="alert"',
    );
    expect(manager).toContain(
      '"common.retry"',
    );
    expect(manager).toContain(
      "setReloadToken(",
    );
    expect(manager).toContain(
      'aria-live="polite"',
    );
  });
});
