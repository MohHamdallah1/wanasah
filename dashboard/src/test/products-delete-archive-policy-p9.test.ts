import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

const readSource = (
  relativePath: string,
): string =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

const compact = (
  value: string,
): string =>
  value
    .replace(/\s+/g, " ")
    .trim();

describe("Products P9 delete/archive policy", () => {
  it("keeps permanent deletion out of normal Product Details", () => {
    const manager = compact(
      readSource(
        "../pages/products/lifecycle/ProductLifecycleManager.tsx",
      ),
    );

    expect(manager).toContain(
      "<CatalogLifecycleActions",
    );
    expect(manager).not.toContain(
      "onVariantDeleted=",
    );
  });

  it("requires a current backend preflight before advanced draft deletion", () => {
    const actions = compact(
      readSource(
        "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
      ),
    );

    expect(actions).toContain(
      "delete-draft-preflight",
    );
    expect(actions).toContain(
      "deletePreflight?.can_delete",
    );
    expect(actions).toContain(
      "deletePreflightRequired",
    );
    expect(actions).toContain(
      'runCommand( "delete-draft", )',
    );
  });

  it("parses blocker-aware draft-delete preflight responses", () => {
    const contracts = compact(
      readSource(
        "../pages/inventory/catalog/contracts.ts",
      ),
    );

    expect(contracts).toContain(
      "export interface DraftDeletePreflight",
    );
    expect(contracts).toContain(
      "parseDraftDeletePreflight",
    );
    expect(contracts).toContain(
      "can_delete",
    );
    expect(contracts).toContain(
      "blockers",
    );
  });

  it("keeps archive as the lifecycle path for used products", () => {
    const actions = compact(
      readSource(
        "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
      ),
    );

    expect(actions).toContain(
      '"retire"',
    );
    expect(actions).toContain(
      '"archive"',
    );
    expect(actions).toContain(
      "archive-preflight",
    );
    expect(actions).toContain(
      "preflight?.can_archive",
    );
  });
});
