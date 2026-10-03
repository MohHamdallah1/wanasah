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

  it("shows product status and sales status inside the simple action surface", () => {
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    const panel = read("../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx");
    expect(manager).not.toContain("ProductLifecycleStatusRail");
    expect(panel).toContain("products.details.lifecycleModes.");
    expect(panel).toContain("products.details.holdModes.");
    expect(panel).not.toContain("variant.version");
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
