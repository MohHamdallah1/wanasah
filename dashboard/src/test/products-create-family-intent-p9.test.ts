import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import type {
  ProductFamily,
} from "../pages/products/contracts";
import {
  resolveCreateProductFamilyIntent,
} from "../pages/products/create/createProductFamilyIntent";
import {
  emptyDraft,
} from "../pages/products/create/useCreateProductState";

const families: ProductFamily[] = [
  {
    id: 7,
    name: "Chips",
    version: 3,
    variant_count: 4,
  },
];

const readSource = (
  relativePath: string,
) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products P9 create family intent", () => {
  it("creates no implicit family when family mode is none", () => {
    expect(
      resolveCreateProductFamilyIntent(
        emptyDraft,
        families,
      ),
    ).toEqual({
      ok: true,
      family_id: null,
      family_name: null,
    });
  });

  it("sends an explicit existing family id and never a new family name", () => {
    expect(
      resolveCreateProductFamilyIntent(
        {
          ...emptyDraft,
          family_mode: "existing",
          family_id: 7,
          family: "Chips",
        },
        families,
      ),
    ).toEqual({
      ok: true,
      family_id: 7,
      family_name: null,
    });
  });

  it("can resolve an exact existing family option without turning a typo into a new family", () => {
    expect(
      resolveCreateProductFamilyIntent(
        {
          ...emptyDraft,
          family_mode: "existing",
          family: " chips ",
        },
        families,
      ),
    ).toEqual({
      ok: true,
      family_id: 7,
      family_name: null,
    });

    expect(
      resolveCreateProductFamilyIntent(
        {
          ...emptyDraft,
          family_mode: "existing",
          family: "Chip",
        },
        families,
      ),
    ).toEqual({
      ok: false,
      error:
        "EXISTING_FAMILY_REQUIRED",
    });
  });

  it("creates a new family only when the user explicitly chose new family", () => {
    expect(
      resolveCreateProductFamilyIntent(
        {
          ...emptyDraft,
          family_mode: "new",
          family: "Snacks",
        },
        families,
      ),
    ).toEqual({
      ok: true,
      family_id: null,
      family_name: "Snacks",
    });

    expect(
      resolveCreateProductFamilyIntent(
        {
          ...emptyDraft,
          family_mode: "new",
          family: " ",
        },
        families,
      ),
    ).toEqual({
      ok: false,
      error:
        "NEW_FAMILY_NAME_REQUIRED",
    });
  });

  it("keeps existing and new family choices visibly separate in Quick Create", () => {
    const identity = readSource(
      "../pages/products/create/CreateProductIdentitySection.tsx",
    );
    const mutation = readSource(
      "../pages/products/create/useCreateProductMutation.ts",
    )
      .replace(/\s+/g, " ")
      .trim();

    expect(identity).toContain(
      'role="group"',
    );
    expect(identity).toContain(
      '"products.familyModeLabel"',
    );
    expect(identity).toContain(
      '"products.familyExistingPlaceholder"',
    );
    expect(identity).toContain(
      '"products.familyNewPlaceholder"',
    );
    expect(identity).toContain(
      '"products.familyExistingHint"',
    );
    expect(identity).toContain(
      '"products.familyNewHint"',
    );
    expect(mutation).toContain(
      "family_id: familyIntent.family_id",
    );
    expect(mutation).toContain(
      "family_name: familyIntent.family_name",
    );
  });
});
