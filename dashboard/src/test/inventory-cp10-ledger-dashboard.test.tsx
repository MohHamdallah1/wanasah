import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { createStocktakeLedgerReferenceTarget } from "@/pages/inventory/ledger/stocktakeLedgerNavigation";

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
  available_types: ["TRANSFER", "INBOUND_SUPPLIER", "AUDIT_ADJUSTMENT"],
});

const renderLedger = (locationId = 11, initialEntry = "/inventory") => render(
  <MemoryRouter initialEntries={[initialEntry]}>
    <Tab4Ledger locationId={locationId} refreshKey={0} onInventoryChanged={() => undefined} />
  </MemoryRouter>,
);

function LedgerModeHarness() {
  const navigate = useNavigate();
  const [warehouse, setWarehouse] = useState(11);
  return <>
    <button type="button" onClick={() => {
      const target = createStocktakeLedgerReferenceTarget({ locationId: 11, reference: "STK-ABC" });
      navigate({ pathname: target.pathname, search: target.search }, { state: target.state });
    }}>Open exact STK</button>
    <button type="button" onClick={() => setWarehouse(12)}>Switch warehouse</button>
    <button type="button" onClick={() => setWarehouse(11)}>Restore warehouse</button>
    <Tab4Ledger locationId={warehouse} refreshKey={0} onInventoryChanged={() => undefined} />
  </>;
}
const renderLedgerMode = () => render(
  <MemoryRouter initialEntries={["/inventory"]}>
    <LedgerModeHarness />
  </MemoryRouter>,
);

beforeEach(() => {
  mocks.authFetch.mockReset();
  mocks.language = "en";
  mocks.permissions = new Set(["ledger.read", "ledger.adjust"]);
});

describe("CP10 Ledger Dashboard", () => {
  it("filters the exact STK reference and clears it without leaking prior rows", async () => {
    const lookup: string[] = [];
    mocks.authFetch.mockImplementation(async (path: string) => {
      const params = new URLSearchParams(path.split("?")[1]);
      if (path.startsWith("/warehouse/ledger/cursor?")) {
        lookup.push(path);
        if (params.get("reference_id") === "STK-ABC") return page([entry(91, {
          type: "AUDIT_ADJUSTMENT", reference_type: "AUDIT_ADJUSTMENT",
          reference: "STK-ABC", quantity: "-2",
        })]);
        return page([]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    renderLedger(11, "/inventory?ledger_ref=STK-ABC&ledger_location=11");
    expect(await screen.findAllByText("Stocktake adjustment")).not.toHaveLength(0);
    expect(lookup.some(path => path.includes("reference_type=AUDIT_ADJUSTMENT") &&
      path.includes("reference_id=STK-ABC") && path.includes("location_id=11"))).toBe(true);
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "Show all movements"}));
    expect(await screen.findByRole("searchbox")).toBeInTheDocument();
  });

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


  it.each(["ar", "en"] as const)(
    "separates paged fuzzy STK search from exact STK reference, then restores fuzzy mode in %s",
    async language => {
      mocks.language = language;
      const calls: string[] = [];
      const baseAdjustment = {
        type: "AUDIT_ADJUSTMENT",
        reference_type: "AUDIT_ADJUSTMENT",
        reference: "STK-ABC",
        quantity: "-2",
        balance_before: "9",
        balance_after: "7",
        batch_number: "REAL-LOT-9",
        source_stock_status: "AVAILABLE",
        destination_stock_status: "AVAILABLE",
      };
      mocks.authFetch.mockImplementation(async (url: string) => {
        if (!url.startsWith("/warehouse/ledger/cursor?")) {
          throw Error("Unexpected query: " + url);
        }
        calls.push(url);
        const q = new URL(url, "https://ledger.test").searchParams;
        if (q.get("location_id") !== "11") throw { status: 403 };
        if (q.has("reference_id")) {
          if (q.get("cursor") || q.has("search") || q.get("reference_id") !== "STK-ABC" ||
              q.get("reference_type") !== "AUDIT_ADJUSTMENT") {
            throw Error("Exact lookup reused a fuzzy search cursor or filters");
          }
          return page([entry(903, { ...baseAdjustment, product_name: "Exact posted adjustment" })]);
        }
        if (q.get("search") === "STK-ABC" && q.get("reference_type") === "AUDIT_ADJUSTMENT") {
          if (q.get("cursor") === "fuzzy-next") {
            return page([entry(902, { ...baseAdjustment,
              reference: "STK-ABC-SIMILAR", product_name: "Fuzzy page two" })]);
          }
          return page([entry(901, { ...baseAdjustment,
            reference: "STK-ABC-SIMILAR", product_name: "Fuzzy page one" })], "fuzzy-next");
        }
        return page([], null);
      });
      const { container } = renderLedgerMode();
      const searchLabel = language === "ar"
        ? "ابحث بالمنتج أو المرجع أو المنفذ..."
        : "Search product, reference, or actor...";
      const movementLabel = language === "ar" ? "الحركة" : "Movement";
      fireEvent.change(screen.getByRole("searchbox", { name: searchLabel }), {
        target: { value: "STK-ABC" },
      });
      await waitFor(() => expect(calls.some(call => call.includes("search=STK-ABC"))).toBe(true));
      await waitFor(() => expect(screen.getByRole("option", {
        name: language === "ar" ? "تسوية جرد" : "Stocktake adjustment",
      })).toBeInTheDocument());
      fireEvent.change(screen.getByRole("combobox", { name: movementLabel }), {
        target: { value: "AUDIT_ADJUSTMENT" },
      });
      expect(await screen.findAllByText("Fuzzy page one")).not.toHaveLength(0);
      const nextLabel = language === "ar" ? "الصفحة التالية" : "Next page";
      fireEvent.click(screen.getByRole("button", { name: nextLabel }));
      expect(await screen.findAllByText("Fuzzy page two")).not.toHaveLength(0);
      expect(calls.some(call => call.includes("cursor=fuzzy-next"))).toBe(true);

      fireEvent.click(screen.getByRole("button", { name: "Open exact STK" }));
      // The scope identity changes synchronously, before the new HTTP resolves.
      expect(screen.queryByText("Fuzzy page two")).not.toBeInTheDocument();
      expect(await screen.findAllByText("Exact posted adjustment")).not.toHaveLength(0);
      expect(screen.queryByText("Fuzzy page one")).not.toBeInTheDocument();
      expect(screen.queryByText("Fuzzy page two")).not.toBeInTheDocument();
      const exactCalls = calls.filter(call => call.includes("reference_id=STK-ABC"));
      expect(exactCalls.length).toBeGreaterThan(0);
      expect(exactCalls.every(call => !call.includes("cursor=") && !call.includes("search="))).toBe(true);
      expect(container.querySelector(".hidden.md\\:block")).not.toBeNull();
      expect(container.querySelector(".md\\:hidden")).not.toBeNull();
      fireEvent.click(screen.getByRole("button", {
        name: language === "ar" ? "عرض جميع الحركات" : "Show all movements",
      }));
      expect(await screen.findAllByText("Fuzzy page one")).not.toHaveLength(0);
      expect(screen.queryByText("Exact posted adjustment")).not.toBeInTheDocument();
      expect(calls.at(-1)).toContain("search=STK-ABC");
      expect(calls.at(-1)).not.toContain("reference_id=");
      expect(calls.at(-1)).not.toContain("cursor=");
    },
  );

  it("rejects stale fuzzy responses and foreign warehouse during exact lookup", async () => {
    let resolveOld: ((data: unknown) => void) | null = null;
    const delayed = new Promise<unknown>(resolve => { resolveOld = resolve; });
    const calls: string[] = [];
    const exact = entry(808, {
      type: "AUDIT_ADJUSTMENT", reference_type: "AUDIT_ADJUSTMENT",
      product_name: "Authorized exact batch", reference: "STK-ABC",
      quantity: "-2", balance_before: "12", balance_after: "10",
      batch_number: "EXACT-LOT-1", source_stock_status: "QUARANTINED",
    });
    mocks.authFetch.mockImplementation(async (url: string) => {
      if (!url.startsWith("/warehouse/ledger/cursor?")) throw Error("Unexpected query " + url);
      calls.push(url);
      const q = new URL(url, "https://ledger.test").searchParams;
      if (q.get("location_id") === "12") throw { status: 403 };
      if (q.get("reference_id") === "STK-ABC") return page([exact]);
      if (q.get("search") === "STK-ABC") return delayed;
      return page([]);
    });
    renderLedgerMode();
    fireEvent.change(screen.getByRole("searchbox", {
      name: "Search product, reference, or actor...",
    }), { target: { value: "STK-ABC" } });
    await waitFor(() => expect(calls.some(call => call.includes("search=STK-ABC"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Open exact STK" }));
    expect(await screen.findAllByText("Authorized exact batch")).not.toHaveLength(0);
    resolveOld?.(page([entry(807, { product_name: "Stale fuzzy result" })]));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(screen.queryByText("Stale fuzzy result")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch warehouse" }));
    expect(screen.queryByText("Authorized exact batch")).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some(call => call.includes("location_id=12"))).toBe(true));
    expect(screen.queryByText("Authorized exact batch")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /STK-ABC/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore warehouse" }));
    expect(await screen.findAllByText("Authorized exact batch")).not.toHaveLength(0);
    const scoped = calls.filter(call => call.includes("reference_id=STK-ABC"));
    expect(scoped.every(call => call.includes("location_id=11"))).toBe(true);
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
    rendered.rerender(
      <MemoryRouter initialEntries={["/inventory"]}>
        <Tab4Ledger locationId={12} refreshKey={0} onInventoryChanged={() => undefined} />
      </MemoryRouter>,
    );
    expect(await screen.findAllByText("Warehouse A2 Product")).not.toHaveLength(0);
    resolveOld?.(page([entry(11, { product_name: "Stale A1 Product" })]));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("Stale A1 Product")).not.toBeInTheDocument();
  });
});
