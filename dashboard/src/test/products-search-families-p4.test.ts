import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import {
  parseProductFamilies,
  parseProductFamilyMutation,
  parseSimpleProductPage,
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

    it("accepts bounded scoped product cursors up to the API limit", () => {
      const longCursor =
        "x".repeat(1500);
      expect(
        parseSimpleProductPage({
          currency_code: "JOD",
          pricing_visible: false,
          items: [],
          next_cursor: longCursor,
          has_more: true,
        }).next_cursor,
      ).toBe(longCursor);

      expect(() =>
        parseSimpleProductPage({
          currency_code: "JOD",
          pricing_visible: false,
          items: [],
          next_cursor:
            "x".repeat(2049),
          has_more: true,
        }),
      ).toThrow(
        "SIMPLE_PRODUCTS_RESPONSE_INVALID",
      );
    });

    it("wires every P4.2 filter and stable sort into the server query scope", () => {
      const page = compact(
        readSource(
          "../pages/ProductsDashboard.tsx",
        ),
      );
      const filters = compact(
        readSource(
          "../pages/products/list/ProductsFiltersPanel.tsx",
        ),
      );
      const listState = compact(
        readSource(
          "../pages/products/list/useProductsListState.ts",
        ),
      );
      const listParams = compact(
        readSource(
          "../pages/products/list/useProductsListParams.ts",
        ),
      );
      const listQueries = compact(
        readSource(
          "../pages/products/list/useProductsListQueries.ts",
        ),
      );
      const listActions = compact(
        readSource(
          "../pages/products/list/createProductsListActions.ts",
        ),
      );
      const translations =
        readSource(
          "../i18n/resources.ts",
        );

      for (const parameter of [
        "family_id",
        "lifecycle",
        "tracking_type",
        "simple_compatible",
        "has_barcode",
        "has_price",
        "lot_tracked",
        "expiry_tracked",
      ]) {
        expect(listParams).toContain(
          `"${parameter}"`,
        );
      }
      expect(listParams).toContain(
        "sort_by: sortBy",
      );
      expect(listParams).toContain(
        "sort_dir: sortDir",
      );

      expect(listQueries).toContain(
        'queryKey: [ "simple-products", companyId, params, ]',
      );
      expect(listQueries).toContain(
        '"filter-options", familyFilterSearch',
      );
      expect(listParams).toContain(
        'limit: "50"',
      );
      expect(listParams).toContain(
        "canViewPricing && priceFilter",
      );
      expect(page).toContain(
        "canViewPricing",
      );
      expect(filters).toContain(
        "{canViewPricing ? (",
      );
      expect(listState).toContain(
        "const resetProductPagination = () => { setCursor(null); setHistory([]); };",
      );
      expect(
        listActions.match(
          /resetProductPagination\(\)/g,
        )?.length ?? 0,
      ).toBeGreaterThanOrEqual(10);
      expect(listQueries).not.toContain(
        "/simple-products/families?limit=200",
      );
      expect(translations).toContain(
        'show: "الفلاتر والفرز"',
      );
      expect(translations).toContain(
        'show: "Filters & sorting"',
      );
    });

    it("keeps the price-filter plan-cache override surgical and reset", () => {
      const api = compact(
        readSource(
          "../../../wa_backend/api/simple_products.py",
        ),
      );

      expect(api).toContain(
        "force_custom_price_plan = ( has_price is not None and book is not None )",
      );
      expect(api).toContain(
        '"SET LOCAL plan_cache_mode = "',
      );
      expect(api).toContain(
        '"\'force_custom_plan\'"',
      );
      expect(api).toContain(
        "previous_plan_cache_mode = str(",
      );
      expect(api).toContain(
        "SHOW plan_cache_mode",
      );
      expect(api).toContain(
        '"SELECT set_config("',
      );
      expect(api).toContain(
        '":previous_plan_cache_mode, "',
      );
      expect(
        api.indexOf(
          '"SET LOCAL plan_cache_mode = "',
        ),
      ).toBeLessThan(
        api.indexOf(
          "stmt.order_by( *ordering ).limit(limit + 1)",
        ),
      );
      expect(
        api.indexOf(
          '"SELECT set_config("',
        ),
      ).toBeGreaterThan(
        api.indexOf(
          "stmt.order_by( *ordering ).limit(limit + 1)",
        ),
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

    it("searches product identity through the RLS-safe native trigram function", () => {
      const api = compact(
        readSource(
          "../../../wa_backend/api/simple_products.py",
        ),
      );
      const migration = compact(
        readSource(
          "../../../wa_backend/alembic/versions/c1f4e8a2d6b9_simple_products_native_trgm_search.py",
        ),
      );

      expect(api).toContain(
        "simple_products_search_variant_ids(",
      );
      expect(api).toContain(
        "simple_products_search_patterns",
      );
      expect(api).toContain(
        "ARRAY(String())",
      );
      expect(api).toContain(
        "_escaped_like(token)",
      );
      expect(api).toContain(
        "ProductVariant.id.in_(",
      );

      expect(migration).toContain(
        "SECURITY DEFINER",
      );
      expect(migration).toContain(
        "SET row_security = off",
      );
      expect(migration).toContain(
        "expected_company_id IS DISTINCT FROM tenant_id",
      );
      expect(migration).toContain(
        "FROM public.product_variants AS pv",
      );
      expect(migration).toContain(
        "FROM public.products AS p",
      );
      expect(migration).toContain(
        "FROM public.product_barcodes AS pb",
      );
      expect(migration).toContain(
        "UNION",
      );
      expect(migration).toContain(
        "INTERSECT",
      );
      expect(migration).toContain(
        "pb.is_active IS TRUE",
      );
      expect(migration).toContain(
        "pb.valid_from <= $2",
      );
      expect(migration).toContain(
        "pb.valid_to > $2",
      );
      expect(migration).toContain(
        "REVOKE ALL ON FUNCTION",
      );
      expect(migration).toContain(
        "GRANT EXECUTE ON FUNCTION",
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
      const toolbar = compact(
        readSource(
          "../pages/products/list/ProductsListToolbar.tsx",
        ),
      );
      const createFamilyQuery = compact(
        readSource(
          "../pages/products/create/useCreateFamilyOptionsQuery.ts",
        ),
      );
      const createModal = compact(
        readSource(
          "../pages/products/create/CreateProductModal.tsx",
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
      expect(createFamilyQuery).toContain(
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
      expect(createFamilyQuery).not.toContain(
        "/simple-products/families?limit=200",
      );
      expect(manager).not.toContain(
        "/simple-products/families?limit=200",
      );
      expect(createModal).toContain(
        "{familyOptions.map(",
      );
      expect(page).toContain(
        "<ProductFamiliesManager",
      );
      expect(toolbar).toContain(
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
