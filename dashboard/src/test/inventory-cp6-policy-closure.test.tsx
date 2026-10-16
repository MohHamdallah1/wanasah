import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ authFetch: vi.fn() }));

vi.mock("@/hooks/useAuthFetch", () => ({
  useAuthFetch: () => mocks.authFetch,
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (_key: string, options?: { defaultValue?: string }) =>
        options?.defaultValue ?? _key,
      i18n: {
        dir: () => "ltr",
        language: "en",
        resolvedLanguage: "en",
      },
    }),
  };
});

import { ShelfLifePolicyExplainability } from "@/pages/inventory/stock-policy/ShelfLifePolicyExplainability";
import { parseEffectiveShelfLifePolicy } from "@/pages/inventory/stock-policy/contracts";

const LOCATION = 55;
const VARIANT = 11;

const policy = {
  location_id: LOCATION,
  product_variant_id: VARIANT,
  minimum_remaining_shelf_life_days: 10,
  requirement_applies: true,
  source: "EXACT_ACTIVE_POLICY",
  management_mode: "READ_ONLY_V1",
};

const batch = {
  batch_id: 901,
  batch_number: "LOT-901",
  production_date: "2026-10-01",
  expiry_date: "2026-10-25",
  disposition: "RELEASED",
  disposition_reason: null,
  disposition_revision: 1,
  allowed_disposition_targets: ["QUARANTINED", "BLOCKED", "RECALLED"],
  days_to_expiry: 9,
  product_id: 3,
  product_variant_id: VARIANT,
  product_name: "Policy product",
  sku: "SKU-11",
  family_name: "Policy family",
  lot_control_mode: "REQUIRED",
  expiry_control_mode: "REQUIRED",
  minimum_remaining_shelf_life_days: 10,
  sellability_state: "NOT_SELLABLE",
  sellability_reason_codes: ["MINIMUM_REMAINING_SHELF_LIFE_NOT_MET"],
  base_uom_id: 1,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 1,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  quantity_scale: 0,
  quantity_step: "1",
  on_hand_quantity: "4",
  reserved_quantity: "0",
  available_for_sale_quantity: "0",
  unavailable_quantity: "4",
  available_status_quantity: "4",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
};

const batchPage = {
  location_id: LOCATION,
  as_of_date: "2026-10-16",
  items: [batch],
  next_cursor: null,
  has_more: false,
};

describe("CP6.2/6.3 policy closure Dashboard", () => {
  beforeEach(() => {
    mocks.authFetch.mockReset();
    mocks.authFetch.mockImplementation(async (url: string, options?: RequestInit) => {
      expect(options?.method).toBeUndefined();
      if (url.startsWith("/warehouse/inventory/stock-policy/effective?")) return policy;
      if (url.startsWith("/warehouse/inventory/batches/cursor?")) return batchPage;
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  it("renders only server-provided effective policy, remaining days, sellability and reason code", async () => {
    render(
      <ShelfLifePolicyExplainability
        locationId={LOCATION}
        productVariantId={VARIANT}
      />,
    );

    expect(await screen.findByText("Effective shelf-life policy")).toBeTruthy();
    expect(screen.getByText("10 days")).toBeTruthy();
    expect(screen.getByText("9 days")).toBeTruthy();
    expect(screen.getByText("Not sellable")).toBeTruthy();
    expect(screen.getByText(/MINIMUM_REMAINING_SHELF_LIFE_NOT_MET/)).toBeTruthy();
    expect(screen.getByText(/display preference and never changes sellability/i)).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("spinbutton")).toBeNull();

    await waitFor(() => expect(mocks.authFetch).toHaveBeenCalledTimes(2));
    const urls = mocks.authFetch.mock.calls.map(([url]) => String(url));
    expect(urls.every((url) => url.includes(`location_id=${LOCATION}`))).toBe(true);
    expect(urls.every((url) => url.includes(`product_variant_id=${VARIANT}`))).toBe(true);
  });

  it("fails closed on inconsistent read-only policy contracts", () => {
    expect(() => parseEffectiveShelfLifePolicy(policy)).not.toThrow();
    expect(() =>
      parseEffectiveShelfLifePolicy({ ...policy, requirement_applies: false }),
    ).toThrowError(/STOCK_POLICY_RESPONSE_INVALID/);
    expect(() =>
      parseEffectiveShelfLifePolicy({ ...policy, management_mode: "EDITABLE" }),
    ).toThrowError(/STOCK_POLICY_RESPONSE_INVALID/);
    expect(() =>
      parseEffectiveShelfLifePolicy({
        ...policy,
        minimum_remaining_shelf_life_days: 1.5,
      }),
    ).toThrowError(/STOCK_POLICY_RESPONSE_INVALID/);
  });

  it("keeps explainability modular, responsive, bilingual-ready, keyboard-safe, and free of cost reconstruction", () => {
    const read = (path: string) =>
      readFileSync(resolve(process.cwd(), "src", path), "utf8");
    const manager = read("pages/inventory/StockMinimumManager.tsx");
    const explain = read("pages/inventory/stock-policy/ShelfLifePolicyExplainability.tsx");
    const policyI18n = read("pages/inventory/stock-policy/i18n.ts");
    const contract = read("pages/inventory/stock-policy/contracts.ts");

    expect(manager).toContain('from "./stock-policy/ShelfLifePolicyExplainability"');
    expect(manager).toContain("<ShelfLifePolicyExplainability");
    expect(explain).toContain('import { useShelfLifePolicyCopy } from "./i18n"');
    expect(explain).toContain("useShelfLifePolicyCopy()");
    expect(policyI18n).toContain("ar: {");
    expect(policyI18n).toContain("en: {");
    expect(policyI18n).toContain('title: "سياسة مدة الصلاحية الفعالة"');
    expect(policyI18n).toContain('title: "Effective shelf-life policy"');
    expect(policyI18n).toContain('locale: isArabic ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn"');
    expect(explain).toContain('numberingSystem: "latn"');
    expect(explain).toContain("sm:grid-cols-2");
    expect(explain).toContain("xl:grid-cols-3");
    expect(explain).toContain('type="button"');
    expect(explain).toContain("focus-visible:ring-2");
    expect(policyI18n).toContain("server result");
    expect(policyI18n).toContain("Server code");
    expect(explain).toContain("text.sampleTitle");
    expect(explain).toContain("text.reasonCode");
    expect(contract).toContain('management_mode: "READ_ONLY_V1"');

    for (const forbidden of [
      "average_cost_display",
      "last_purchase_cost",
      "latest_purchase_cost",
      "input_unit_cost",
      "total_cost",
      "average_cost_after",
    ]) {
      expect(explain).not.toContain(forbidden);
    }
    expect(explain).not.toMatch(/\bparseFloat\b|\bNumber\([^)]*cost|\bcost\s*[+*\/-]/i);
  });
});
