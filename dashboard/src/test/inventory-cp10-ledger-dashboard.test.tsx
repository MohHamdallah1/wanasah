import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LedgerEntry } from "@/pages/inventory/ledger/contracts";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  language: "en",
  permissions: new Set<string>(["ledger.read", "ledger.adjust"]),
}));

vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => mocks.authFetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({
  useInventoryAccess: () => ({
    can: (code: string) => mocks.permissions.has(code),
    isSuccess: true,
    data: { company_id: 1, backoffice_user_id: 7 },
  }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  const copy: Record<string, string> = { "common.close": "Close" };
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, options?: Record<string, unknown>) => {
        let value = typeof options?.defaultValue === "string" ? options.defaultValue : copy[key] ?? key;
        for (const [name, candidate] of Object.entries(options ?? {})) {
          value = value.replaceAll(`{{${name}}}`, String(candidate));
        }
        return value;
      },
      i18n: {
        language: mocks.language,
        resolvedLanguage: mocks.language,
        dir: () => (mocks.language === "ar" ? "rtl" : "ltr"),
      },
    }),
  };
});

import { Tab4Ledger } from "@/pages/inventory/Tab4Ledger";

const entry = (id: number, overrides: Partial<LedgerEntry> = {}): LedgerEntry => ({
  id,
  product_variant_id: 100,
  product_name: "Shared Product",
  base_uom_id: 1,
  base_uom_code: "EACH",
  quantity_scale: 6,
  quantity_step: "0.000001",
  type: "TRANSFER",
  reference_type: "TRANSFER",
  movement_kind: "PHYSICAL",
  quantity: "2.500001",
  balance_before: "5",
  balance_after: "7.500001",
  balance_scope: "PRODUCT_LOCATION",
  batch_id: 22,
  batch_number: "LOT-SHARED",
  source_location_id: 11,
  source_location_name: "Warehouse A1",
  destination_location_id: 12,
  destination_location_name: "Warehouse A2",
  source_stock_status: "AVAILABLE",
  destination_stock_status: "AVAILABLE",
  display_uom_id: 1,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  currency_code: "JOD",
  cost_method: null,
  input_quantity: null,
  input_uom_code: null,
  input_uom_name: null,
  input_unit_cost: null,
  total_cost: null,
  average_cost_after: null,
  average_cost_uom_code: null,
  average_cost_uom_name: null,
  admin_name: "Operator",
  reference: "REF-SHARED",
  notes: "Evidence note",
  supplier_name: null,
  supplier_code: null,
  supplier_id: null,
  date: "2026-10-16T12:00:00+00:00",
  ...overrides,
});

const page = (items: LedgerEntry[], next: string | null = null) => ({
  items,
  next_cursor: next,
  has_more: next !== null,
  total: items.length,
  available_types: ["TRANSFER", "INBOUND_SUPPLIER"],
});

const renderLedger = (locationId = 11) => render(
  <Tab4Ledger locationId={locationId} refreshKey={0} onInventoryChanged={() => undefined} />,
);

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.language = "en";
  mocks.permissions = new Set(["ledger.read", "ledger.adjust"]);
});

describe("CP10 Ledger Dashboard", () => {
  it("renders LTR desktop/mobile evidence with public nullable lot and native controls", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/warehouse/ledger/cursor?")) return page([entry(1, { batch_number: null })]);
      throw new Error(`Unexpected request: ${path}`);
    });
    const { container } = renderLedger();
    expect(await screen.findAllByText("No lot supplied")).not.toHaveLength(0);
    expect(container.querySelector('[dir="ltr"]')).not.toBeNull();
    expect(container.querySelector(".hidden.md\\:block")).not.toBeNull();
    expect(container.querySelector(".md\\:hidden")).not.toBeNull();
    expect(screen.getByRole("searchbox", { name: "Search product, reference, or actor..." })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Movement" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh movement ledger" })).toBeInTheDocument();
  });

  it("renders Arabic root RTL and Western movement identity digits", async () => {
    mocks.language = "ar";
    mocks.authFetch.mockResolvedValue(page([entry(13, { batch_number: null })]));
    const { container } = renderLedger();
    expect(await screen.findAllByText("بدون تشغيلة")).not.toHaveLength(0);
    expect(container.querySelector('[dir="rtl"]')).not.toBeNull();
    expect(screen.getAllByText("#13").length).toBeGreaterThan(0);
  });

  it("search and filter changes restart from first page without reusing continuation cursor", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      const params = new URLSearchParams(path.split("?")[1]);
      if (params.get("cursor") === "next-1") return page([entry(2)]);
      return page([entry(1)], "next-1");
    });
    renderLedger();
    expect(await screen.findAllByText("Shared Product")).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(mocks.authFetch.mock.calls.some(([path]) => String(path).includes("cursor=next-1"))).toBe(true));

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "alpha" } });
    await waitFor(() => {
      const matching = mocks.authFetch.mock.calls.map(([path]) => String(path)).filter((path) => path.includes("search=alpha"));
      expect(matching.length).toBeGreaterThan(0);
      expect(matching.at(-1)).not.toContain("cursor=");
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Movement" }), { target: { value: "TRANSFER" } });
    await waitFor(() => {
      const matching = mocks.authFetch.mock.calls.map(([path]) => String(path)).filter((path) => path.includes("reference_type=TRANSFER"));
      expect(matching.length).toBeGreaterThan(0);
      expect(matching.at(-1)).not.toContain("cursor=");
    });
  });

  it("reference evidence binds both reference type and id", async () => {
    mocks.authFetch.mockImplementation(async (path: string) => {
      const params = new URLSearchParams(path.split("?")[1]);
      if (params.get("reference_id") === "REF-SHARED") return page([entry(1)]);
      return page([entry(1)]);
    });
    renderLedger();
    expect(await screen.findAllByText("Shared Product")).not.toHaveLength(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Open evidence for reference REF-SHARED" })[0]);
    await waitFor(() => {
      const call = mocks.authFetch.mock.calls.map(([path]) => String(path)).find((path) => path.includes("reference_id=REF-SHARED"));
      expect(call).toContain("reference_type=TRANSFER");
      expect(call).toContain("location_id=11");
    });
  });

  it("read-only user gets no adjustment control", async () => {
    mocks.permissions = new Set(["ledger.read"]);
    mocks.authFetch.mockResolvedValue(page([entry(3, { type: "INBOUND_SUPPLIER", reference_type: "INBOUND_SUPPLIER" })]));
    renderLedger();
    expect(await screen.findAllByText("Shared Product")).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Record inbound correction" })).not.toBeInTheDocument();
  });

  it("adjustment loads authoritative state, focuses quantity, and submits exact decimal total", async () => {
    const inbound = entry(4, { type: "INBOUND_SUPPLIER", reference_type: "INBOUND_SUPPLIER" });
    mocks.authFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.startsWith("/warehouse/ledger/cursor?")) return page([inbound]);
      if (path === "/warehouse/ledger/4/adjustment-state") {
        return {
          entry_id: 4,
          reference: "REF-SHARED",
          product_variant_id: 100,
          batch_id: 22,
          warehouse_location_id: 11,
          current_total_quantity: "10.250001",
          base_uom_id: 1,
          base_uom_code: "EACH",
        };
      }
      if (path === "/warehouse/ledger/4/adjust" && init?.method === "POST") return { message: "saved" };
      throw new Error(`Unexpected request: ${path}`);
    });
    renderLedger();
    expect(await screen.findAllByText("Shared Product")).not.toHaveLength(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Record inbound correction" })[0]);
    const quantity = await screen.findByRole("textbox", { name: "Requested correct total" });
    await waitFor(() => expect(quantity).toHaveFocus());
    expect(quantity).toHaveValue("10.250001");
    fireEvent.change(quantity, { target: { value: "8.000001" } });
    expect(await screen.findByText("-2.25 EACH")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Confirmation password"), { target: { value: "secret" } });
    fireEvent.submit(quantity.closest("form")!);
    await waitFor(() => {
      const post = mocks.authFetch.mock.calls.find(([path, init]) => path === "/warehouse/ledger/4/adjust" && init?.method === "POST");
      expect(post).toBeTruthy();
      expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
        new_total_quantity: "8.000001",
        uom_id: 1,
        password: "secret",
      });
    });
  });

  it("stale Warehouse response cannot overwrite a newer Warehouse scope", async () => {
    let resolveOld: ((value: unknown) => void) | null = null;
    const old = new Promise((resolve) => { resolveOld = resolve; });
    mocks.authFetch.mockImplementation(async (path: string) => {
      if (path.includes("location_id=11")) return old;
      if (path.includes("location_id=12")) return page([entry(12, { product_name: "Warehouse A2 Product" })]);
      throw new Error(`Unexpected request: ${path}`);
    });
    const rendered = renderLedger(11);
    rendered.rerender(<Tab4Ledger locationId={12} refreshKey={0} onInventoryChanged={() => undefined} />);
    expect(await screen.findAllByText("Warehouse A2 Product")).not.toHaveLength(0);
    resolveOld?.(page([entry(11, { product_name: "Stale A1 Product" })]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Stale A1 Product")).not.toBeInTheDocument();
  });
});
