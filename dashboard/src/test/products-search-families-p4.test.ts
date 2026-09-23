import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import {
  parseProductFamilies,
  parseProductFamilyMutation,
} from "../pages/products/contracts";

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
  value.replace(/\s+/g, " ").trim();

describe(
  "Products P4 search and families contracts",
  () => {
    it("parses bounded family cursor pages strictly", () => {
      const page =
        parseProductFamilies({
          items: [
            {
              id: 1,
              name: "Family A",
              version: 2,
              variant_count: 3,
            },
          ],
          next_cursor: "signed.cursor",
          has_more: true,
        });

      expect(page.items).toHaveLength(
        1,
      );
      expect(
        page.next_cursor,
      ).toBe("signed.cursor");
      expect(page.has_more).toBe(
        true,
      );

      expect(() =>
        parseProductFamilies({
          items: [],
          next_cursor: null,
          has_more: true,
        }),
      ).toThrow(
        "PRODUCT_FAMILIES_RESPONSE_INVALID",
      );

      expect(() =>
        parseProductFamilies({
          items: [],
          next_cursor:
            "unexpected.cursor",
          has_more: false,
        }),
      ).toThrow(
        "PRODUCT_FAMILIES_RESPONSE_INVALID",
      );

      const longCursor =
        "x".repeat(1500);
      expect(
        parseProductFamilies({
          items: [],
          next_cursor: longCursor,
          has_more: true,
        }).next_cursor,
      ).toBe(longCursor);

      expect(() =>
        parseProductFamilies({
          items: [],
          next_cursor:
            "x".repeat(2049),
          has_more: true,
        }),
      ).toThrow(
        "PRODUCT_FAMILIES_RESPONSE_INVALID",
      );
    });

    it("validates family mutation responses at the frontend boundary", () => {
      expect(
        parseProductFamilyMutation({
          id: 7,
          name: "Family A",
          version: 3,
          variant_count: 4,
        }),
      ).toEqual({
        id: 7,
        name: "Family A",
        version: 3,
      });

      expect(() =>
        parseProductFamilyMutation({
          id: 7,
          name: "Family A",
          version: 0,
        }),
      ).toThrow(
        "PRODUCT_FAMILY_MUTATION_RESPONSE_INVALID",
      );
    });

    it("searches product identity through name family SKU and active barcode with AND token semantics", () => {
      const api = compact(
        readSource(
          "../../../wa_backend/api/simple_products.py",
        ),
      );

      expect(api).toContain(
        "for token in _search_tokens(search):",
      );
      expect(api).toContain(
        "ProductVariant.sku",
      );
      expect(api).toContain(
        "ProductBarcode.product_variant_id == ProductVariant.id",
      );
      expect(api).toContain(
        "ProductBarcode.company_id == company_id",
      );
      expect(api).toContain(
        "ProductBarcode.is_active.is_(True)",
      );
      expect(api).toContain(
        "ProductBarcode.valid_from <= barcode_now",
      );
      expect(api).toContain(
        "ProductBarcode.valid_to > barcode_now",
      );
      expect(api).toContain(
        "ProductBarcode.barcode",
      );
      expect(api).toContain(
        "_escaped_like(token)",
      );
    });

    it("uses signed keyset family pagination and never restores the old 200-row load-all query", () => {
      const api = compact(
        readSource(
          "../../../wa_backend/api/simple_products.py",
        ),
      );
      const service = compact(
        readSource(
          "../../../wa_backend/domains/simple_products/service.py",
        ),
      );
      const page = compact(
        readSource(
          "../pages/ProductsDashboard.tsx",
        ),
      );
      const manager = compact(
        readSource(
          "../pages/products/ProductFamiliesManager.tsx",
        ),
      );

      expect(api).toContain(
        "_family_cursor(",
      );
      expect(api).toContain(
        "_family_next_cursor(",
      );
      expect(service).toContain(
        "name_key = func.lower(Product.name)",
      );
      expect(service).toContain(
        "Product.id > int(after_id)",
      );
      expect(manager).toContain(
        'limit: "50"',
      );
      expect(manager).toContain(
        '"manager", search, cursor',
      );
      expect(page).toContain(
        '"options", familyOptionSearch',
      );
      expect(manager).toContain(
        "setCursor(null)",
      );
      expect(manager).toContain(
        "setHistory([])",
      );
      expect(manager).toContain(
        "getOrCreateDurableCommand",
      );
      expect(manager).toContain(
        "readDurableCommand",
      );
      expect(manager).toContain(
        "parseProductFamilyMutation",
      );
      expect(manager).toContain(
        "PRODUCT_FAMILY_MUTATION_RESPONSE_INVALID",
      );
      expect(manager).toContain(
        "isAmbiguousRequestError",
      );
      expect(manager).not.toContain(
        "getOrCreateDurableRequestId",
      );
      expect(service).not.toContain(
        "normalized_after_name",
      );
      expect(page).not.toContain(
        "/simple-products/families?limit=200",
      );
      expect(manager).not.toContain(
        "/simple-products/families?limit=200",
      );
      expect(page).toContain(
        "{familyOptions.map(",
      );
      expect(page).toContain(
        "<ProductFamiliesManager",
      );
      expect(page).toContain(
        'maxLength={100}',
      );
      expect(api).toContain(
        'if key != "_sort_name"',
      );
      expect(service).toContain(
        'name_key.label("sort_name")',
      );
    });

    it("surfaces family load failure separately from empty search results", () => {
      const manager = compact(
        readSource(
          "../pages/products/ProductFamiliesManager.tsx",
        ),
      );
      const translations =
        readSource(
          "../i18n/resources.ts",
        );

      expect(manager).toContain(
        "familiesQuery.isError",
      );
      expect(manager).toContain(
        '"products.errors.familiesLoad"',
      );
      expect(manager).toContain(
        '"products.noMatchingFamilies"',
      );
      expect(manager).toContain(
        "void familiesQuery.refetch()",
      );
      expect(translations).toContain(
        '"ابحث بالمنتج أو العائلة أو SKU أو الباركود..."',
      );
      expect(translations).toContain(
        '"Search by product, family, SKU, or barcode..."',
      );
    });
  },
);
