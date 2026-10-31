import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import type { ReactNode } from "react";
import i18n, { setAppLanguage } from "@/i18n";
import type { PendingRoute } from "@/types/dispatch";
import { AdjustInventoryModal } from "@/components/dispatch/AdjustInventoryModal";
import { TransfersRadarModal } from "@/components/dispatch/TransfersRadarModal";
import { adjustmentReview, buildAdjustmentPayload, parseAdjustLoadInventory } from "@/features/dispatch/adjustLoad";
import { parseRouteTransfers, formatTransferQuantity, transferIsAddition } from "@/features/dispatch/routeTransfers";
import { formatRouteLoadQuantity } from "@/features/dispatch/routeLoadUom";
import { useAdjustLoadCommand } from "@/features/dispatch/useAdjustLoadCommand";
import { durableScope, getOrCreateDurableCommand } from "@/lib/durableOperations";

const fake = vi.hoisted(() => ({ fetch: vi.fn(), online: true, error: vi.fn(), success: vi.fn(), info: vi.fn() }));
let observedBoundaries: { node: Element; callback: IntersectionObserverCallback; observer: IntersectionObserver }[] = [];
class TestIntersectionObserver {
  readonly root = null;
  readonly rootMargin = "1200px 0px";
  readonly thresholds = [0];
  constructor(private callback: IntersectionObserverCallback) {}
  observe = (node: Element) => { observedBoundaries.push({ node, callback: this.callback, observer: this as unknown as IntersectionObserver }); };
  unobserve = () => {};
  disconnect = () => {};
  takeRecords = () => [];
}
async function intersectWindowBoundary(direction: "top" | "bottom") {
  const node = await waitFor(() => {
    const value = document.querySelector(`[data-window-boundary="${direction}"]`);
    if (!value) throw new Error("window boundary not rendered");
    return value;
  });
  const observed = await waitFor(() => {
    const value = [...observedBoundaries].reverse().find((entry) => entry.node === node);
    if (!value) throw new Error("window boundary not observed");
    return value;
  });
  act(() => observed.callback([{ isIntersecting: true, target: node } as IntersectionObserverEntry], observed.observer));
}
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/hooks/useNetworkStatus", () => ({ useNetworkStatus: () => fake.online }));
vi.mock("sonner", () => ({ toast: { error: fake.error, success: fake.success, info: fake.info } }));
vi.mock("@/components/ui/modal", () => ({ Modal: ({ children, isOpen, title }: { children: ReactNode; isOpen: boolean; title: string }) =>
  isOpen ? <div role="dialog" aria-label={title}>{children}</div> : null }));

const inventory = {
  product_id: "701", product_name: "Vermicelli", current_base_quantity: "25", reserved_base_quantity: "0", pending_base_quantity: "0",
  base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "EACH", quantity_scale: 0, quantity_step: "1",
  display_uom_name: "PACK", display_factor_to_base: "8",
  current_cartons: 999, current_packs: 999, packs_per_carton: 999, // Deliberately wrong legacy evidence.
};
const page = (rows: typeof inventory[], next_cursor: string | null = null) => ({
  items: rows.map((load) => ({ id: load.product_id, name: load.product_name, load })), next_cursor, has_more: !!next_cursor,
});
const route: PendingRoute = { id: "9", zoneId: "1", zoneName: "Zone", driverId: "31", driverName: "Rep", vehicleId: "17",
  sourceWarehouseId: "21", workSessionId: null, adjustmentContextRevision: 1,
  shopsRemaining: 2, status: "active", sessionEnded: false, sessionBound: false, can_execute: true, commercial_context: null };

beforeEach(async () => {
  observedBoundaries = [];
  vi.stubGlobal("IntersectionObserver", TestIntersectionObserver);
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  localStorage.clear(); fake.fetch.mockReset(); fake.online = true;
  fake.error.mockClear(); fake.success.mockClear(); fake.info.mockClear();
  await setAppLanguage("en");
});

describe("Canonical Adjust Load quantities and radar", () => {
  it.each([["48000", "10 PALLET"], ["5000", "1 PALLET + 200 EACH"], ["5", "5 EACH"]])(
    "uses server-selected PALLET for %s with only a base remainder", (quantity, expected) => {
      const raw = { ...inventory, current_base_quantity: quantity, display_uom_name: "PALLET", display_factor_to_base: "4800" };
      const item = parseAdjustLoadInventory([raw])[0];
      expect(formatRouteLoadQuantity(item.current_base_quantity, item)).toBe(expected);
      const [transfer] = parseRouteTransfers([{ ...raw, transfer_id: 1, signed_base_quantity: quantity,
        quantity_contract: "CANONICAL_BASE_V1", status: "pending", created_at: null, batch_id: "b", can_force_cancel: true }]);
      expect(formatTransferQuantity(transfer)).toBe(`+${expected.replace("EACH", i18n.t("uom.EACH"))}`);
    });

  it.each([0, 1, -1, 5, -5, 8, -8])("preserves 25 EACH and exact delta %s independently of carton fields", (delta) => {
    const item = parseAdjustLoadInventory([inventory])[0];
    expect(formatRouteLoadQuantity(item.current_base_quantity, item)).toBe("3 PACK + 1 EACH");
    const review = adjustmentReview(item, String(delta));
    expect(review.result).toBe(String(25 + delta));
    expect(review.direction).toBe(delta > 0 ? "ADD" : delta < 0 ? "UNLOAD" : "UNCHANGED");
    const payload = buildAdjustmentPayload([item], { "701": String(delta) });
    expect(JSON.stringify(payload)).not.toContain("delta_cartons");
    expect(payload.deltas).toEqual(delta ? [{ product_id: 701, delta_base: String(delta) }] : []);
  });

  it("handles zero rows and fractional direct quantities but rejects unsupported handshake precision", () => {
    const item = parseAdjustLoadInventory([{ ...inventory, quantity_scale: 2, quantity_step: "0.25" }])[0];
    expect(adjustmentReview(item, "0.5").result).toBe("25.5");
    expect(() => adjustmentReview(item, "0.1")).toThrow();
    expect(() => buildAdjustmentPayload([item], { "701": "0.5" }, true))
      .toThrow(expect.objectContaining({ code: "DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED" }));
    expect(parseAdjustLoadInventory([{ ...inventory, current_base_quantity: "0" }])[0].current_base_quantity).toBe("0");
    const pending = { ...item, pending_base_quantity: "8" };
    expect(adjustmentReview(pending, "5").result).toBe("38");
  });

  it.each([["8", "+1 PACK"], ["5", "+5 EACH"], ["-5", "−5 EACH"], ["25", "+3 PACK + 1 EACH"]])("radar presents exact signed base %s as %s", (value, expected) => {
    const [transfer] = parseRouteTransfers([{ ...inventory, transfer_id: 1, signed_base_quantity: value,
      quantity_contract: "CANONICAL_BASE_V1", status: "pending", created_at: null, batch_id: "b", can_force_cancel: true }]);
    expect(formatTransferQuantity(transfer)).toBe(expected.replace("EACH", i18n.t("uom.EACH")));
    expect(formatTransferQuantity(transfer)).not.toMatch(/carton|كرتونة/);
  });

  it("does not reconstruct a missing canonical radar quantity from legacy fields", () => {
    expect(() => parseRouteTransfers([{ ...inventory, transfer_id: 1, status: "pending", quantity_contract: "CANONICAL_BASE_V1",
      created_at: null, batch_id: "b", can_force_cancel: true }])).toThrow();
  });
});

describe("Adjust Load operator workflow", () => {
  it.each(["en", "ar"] as const)("renders radar from canonical UOM evidence in %s", async (language) => {
    await setAppLanguage(language);
    fake.fetch.mockResolvedValue(["8", "5", "-5"].map((quantity, index) => ({ ...inventory,
      transfer_id: index + 1, signed_base_quantity: quantity, status: "pending", created_at: null,
      quantity_contract: "CANONICAL_BASE_V1",
      batch_id: "b", can_force_cancel: false, delta_cartons: 0, delta_packs: Number(quantity), packs_per_carton: 32,
    })));
    render(<TransfersRadarModal isOpen onClose={vi.fn()} route={route} />);
    expect(await screen.findByText("+1 PACK")).toBeInTheDocument();
    const number = new Intl.NumberFormat(language === "ar" ? "ar-JO-u-nu-latn" : "en-US", { useGrouping: false }).format(5);
    expect(screen.getByText(`+${number} ${i18n.t("uom.EACH")}`)).toBeInTheDocument();
    expect(screen.getByText(`−${number} ${i18n.t("uom.EACH")}`)).toBeInTheDocument();
    expect(screen.queryByText(/كرتونة|carton|999/)).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t("dispatchAdjustLoad.radar.pending"))).toBeInTheDocument();
  });

  it.each(["en", "ar"] as const)("shows current, +5/-5/+8 previews and submits base-only in %s", async (language) => {
    await setAppLanguage(language);
    fake.fetch.mockImplementation(async (url: string) => url.endsWith("live_inventory") ? [inventory] : url.includes("?search=") ? page([]) : { mode: "DIRECT" });
    const success = vi.fn();
    render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={route} onSuccess={success} companyId={1} principalId={3} />);
    const input = await screen.findByRole("spinbutton");
    await waitFor(() => expect(input).not.toBeDisabled());
    const unit = i18n.t("uom.EACH");
    expect(screen.getAllByText(`3 PACK + 1 ${unit}`).length).toBeGreaterThan(0);
    expect(screen.queryByText(/كرتونة|carton/)).not.toBeInTheDocument();
    for (const [delta, expected, direction] of [
      ["5", `3 PACK + 6 ${unit}`, "addDirection"],
      ["-5", `2 PACK + 4 ${unit}`, "unloadDirection"],
      ["8", `4 PACK + 1 ${unit}`, "addDirection"],
    ]) {
      fireEvent.change(input, { target: { value: delta } });
      expect(screen.getByText(expected)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(i18n.t(`dispatchAdjustLoad.${direction}`)))).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.review") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.confirm") }));
    await waitFor(() => expect(success).toHaveBeenCalledOnce());
    const sent = JSON.parse(fake.fetch.mock.calls.find(([url]) => url.endsWith("adjust_inventory"))![1].body);
    expect(sent.deltas).toEqual([{ product_id: 701, delta_base: "8" }]);
    expect(sent.request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(sent).not.toHaveProperty("delta_cartons");
  });

  it.each(["5", "-5"])("normal DIRECT %s never shows recovery while busy or after success", async (delta) => {
    let finish: (value: unknown) => void = () => {};
    fake.fetch.mockImplementation((url: string) => url.endsWith("live_inventory") ? Promise.resolve([inventory]) : url.includes("?search=") ? Promise.resolve(page([]))
      : new Promise((resolve) => { finish = resolve; }));
    const success = vi.fn();
    render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={route} onSuccess={success} companyId={1} principalId={3} />);
    const input = await screen.findByRole("spinbutton");
    await waitFor(() => expect(input).not.toBeDisabled());
    const unknown = i18n.t("dispatchAdjustLoad.unknown");
    expect(screen.queryByText(unknown)).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: delta } });
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm adjustment" }));
    await waitFor(() => expect(fake.fetch.mock.calls.filter(([url]) => url.endsWith("adjust_inventory"))).toHaveLength(1));
    expect(screen.getByText("Applying load adjustment...")).toBeVisible();
    expect(screen.queryByText(unknown)).not.toBeInTheDocument();
    await act(async () => finish({ mode: "DIRECT" }));
    await waitFor(() => expect(success).toHaveBeenCalledOnce());
    expect(screen.queryByText(unknown)).not.toBeInTheDocument();
    expect(fake.fetch.mock.calls.filter(([url]) => url.endsWith("adjust_inventory"))).toHaveLength(1);
  });

  it("shows recovery only after an ambiguous response and retries the identical wire request", async () => {
    fake.fetch.mockImplementation(async (url: string) => {
      if (url.endsWith("live_inventory")) return [inventory];
      if (url.includes("?search=")) return page([]);
      throw { code: "NETWORK_UNAVAILABLE", status: 0 };
    });
    render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={route} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    const input = await screen.findByRole("spinbutton");
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm adjustment" }));
    expect(await screen.findByText(i18n.t("dispatchAdjustLoad.unknown"))).toBeVisible();
    const firstWire = fake.fetch.mock.calls.find(([url]) => url.endsWith("adjust_inventory"))![1].body;
    fake.fetch.mockResolvedValue({ mode: "DIRECT" });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(fake.success).toHaveBeenCalledOnce());
    const sent = fake.fetch.mock.calls.filter(([url]) => url.endsWith("adjust_inventory"));
    expect(sent).toHaveLength(2);
    expect(sent[1][1].body).toBe(firstWire);
    expect(screen.queryByText(i18n.t("dispatchAdjustLoad.unknown"))).not.toBeInTheDocument();
  });

  it("keeps pending net visible and zero adjustment sends no mutation", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("?search=") ? page([]) : [{ ...inventory, pending_base_quantity: "8" }]);
    render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={{ ...route, sessionBound: true }} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    await screen.findByRole("spinbutton");
    await waitFor(() => expect(screen.getByRole("button", { name: "Review changes" })).not.toBeDisabled());
    expect(screen.getByText(/Net pending handshakes/)).toHaveTextContent("1 PACK");
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(fake.info).toHaveBeenCalledWith(i18n.t("dispatchAdjustLoad.empty"));
    expect(fake.fetch.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
});

describe("Bounded Adjust Load discovery", () => {
  const loaded = { ...inventory, product_id: "521", product_name: "Loaded product 521" };
  const extra = { ...inventory, product_id: "900", product_name: "Source warehouse match", current_base_quantity: "0" };
  const open = () => render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={route} onSuccess={vi.fn()} companyId={1} principalId={3} />);

  it("immediately pins Vehicle custody and loads a bounded first source-stock page without typing", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("?search=") ? page([extra]) : [loaded]);
    open();
    await screen.findByText(extra.product_name);
    expect(screen.getByText(loaded.product_name)).toBeVisible();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
    expect(fake.fetch.mock.calls.map(([url]) => url)).toEqual([
      "/dispatch/route/9/live_inventory", "/dispatch/route/9/live_inventory?search=&limit=80",
    ]);
    expect(screen.getAllByRole("heading", { level: 3 }).map((node) => node.textContent)).toEqual([loaded.product_name, extra.product_name]);
    expect(fake.fetch.mock.calls.some(([url]) => url.includes("/dispatch/init"))).toBe(false);
  });

  it("scrolls through 500 source products with a three-page window and keeps drafted rows pinned", async () => {
    const matches = Array.from({ length: 500 }, (_, i) => ({ ...extra, product_id: String(1000 + i), product_name: `Match ${i + 1}` }));
    fake.fetch.mockImplementation(async (url: string) => {
      if (url.endsWith("live_inventory")) return [loaded];
      if (url.endsWith("adjust_inventory")) return { mode: "DIRECT" };
      const cursor = new URL(url, "http://test").searchParams.get("cursor");
      const start = cursor ? Number(cursor.slice(1)) : 0;
      const next = start + 80 < matches.length ? `w${start + 80}` : null;
      return page(matches.slice(start, start + 80), next);
    });
    const view = open();
    await screen.findByText("Match 1");
    expect(screen.queryByRole("button", { name: /Load more|Previous results/ })).not.toBeInTheDocument();

    const firstCard = screen.getByText("Match 1").closest("section")!;
    fireEvent.change(within(firstCard).getByRole("spinbutton"), { target: { value: "2" } });

    for (const expected of [160, 240, 320, 400, 480, 500]) {
      await intersectWindowBoundary("bottom");
      await screen.findByText(`Match ${expected}`);
    }
    expect(screen.getByText("Match 1")).toBeVisible();
    expect(screen.queryByText("Match 2")).not.toBeInTheDocument();
    expect(screen.getByText("Match 500")).toBeVisible();
    expect(view.container.querySelectorAll("[data-window-page]")).toHaveLength(3);
    expect(fake.fetch.mock.calls.filter(([url]) => url.includes("?search=")).every(([url]) => url.includes("limit=80"))).toBe(true);

    const lastCard = screen.getByText("Match 500").closest("section")!;
    fireEvent.change(within(lastCard).getByRole("spinbutton"), { target: { value: "5" } });
    await intersectWindowBoundary("top");
    await screen.findByText("Match 241");
    expect(screen.getByText("Match 1")).toBeVisible();
    expect(screen.getByText("Match 500")).toBeVisible(); // drafted last row remains pinned after its page is evicted
    expect(view.container.querySelectorAll("[data-window-page]")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm adjustment" }));
    await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.endsWith("adjust_inventory"))).toBe(true));
    const sent = JSON.parse(fake.fetch.mock.calls.find(([url]) => url.endsWith("adjust_inventory"))![1].body);
    expect(sent.deltas).toEqual([{ product_id: 1000, delta_base: "2" }, { product_id: 1499, delta_base: "5" }]);
  }, 15_000); // 500-row cursor/DOM acceptance under shared CI runner; preserve every assertion.

  it("debounces paged source search and keeps loaded and drafted rows stable across searches", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("?search=") ? page([extra]) : [loaded]);
    open();
    await screen.findByText(extra.product_name);
    const current = screen.getAllByRole("spinbutton")[0];
    await waitFor(() => expect(current).not.toBeDisabled());
    fireEvent.change(current, { target: { value: "5" } });
    const search = screen.getByRole("textbox", { name: "Search products" });
    fireEvent.change(search, { target: { value: "so" } });
    fireEvent.change(search, { target: { value: "source" } });
    expect(fake.fetch).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(extra.product_name)).toBeVisible();
    await waitFor(() => expect(fake.fetch.mock.calls.filter(([url]) => url.includes("?search=source&"))).toHaveLength(1));
    fireEvent.change(screen.getAllByRole("spinbutton")[1], { target: { value: "2" } });
    fake.fetch.mockImplementation(async () => page([]));
    fireEvent.change(search, { target: { value: "another" } });
    expect(await screen.findByText("No matching eligible products.")).toBeVisible();
    expect(screen.getByText(loaded.product_name)).toBeVisible();
    expect(screen.getByText(extra.product_name)).toBeVisible();
    expect(screen.getAllByRole("spinbutton")[0]).toHaveValue(5);
    expect(screen.getAllByRole("spinbutton")[1]).toHaveValue(2);
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(screen.getByText(`3 PACK + 6 ${i18n.t("uom.EACH")}`)).toBeVisible();
    expect(screen.getByText(extra.product_name)).toBeVisible();
    fake.fetch.mockResolvedValue({ mode: "DIRECT" });
    fireEvent.click(screen.getByRole("button", { name: "Confirm adjustment" }));
    await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.endsWith("adjust_inventory"))).toBe(true));
    const sent = JSON.parse(fake.fetch.mock.calls.find(([url]) => url.endsWith("adjust_inventory"))![1].body);
    expect(sent.deltas).toEqual([{ product_id: 521, delta_base: "5" }, { product_id: 900, delta_base: "2" }]);
  });

  it("discards undrafted search windows and ignores late superseded results", async () => {
    let finish: (raw: unknown) => void;
    fake.fetch.mockImplementation((url: string) => url.includes("search=old")
      ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve(url.includes("search=&") ? page([]) : url.includes("?") ? page([extra]) : [loaded]));
    open();
    await screen.findByText(loaded.product_name);
    const search = screen.getByRole("textbox", { name: "Search products" });
    fireEvent.change(search, { target: { value: "old" } });
    await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.includes("search=old"))).toBe(true));
    fireEvent.change(search, { target: { value: "new" } });
    await screen.findByText(extra.product_name);
    await act(async () => finish!(page([{ ...extra, product_id: "901", product_name: "Stale match" }])));
    expect(screen.queryByText("Stale match")).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.queryByText(extra.product_name)).not.toBeInTheDocument();
    expect(screen.getByText(loaded.product_name)).toBeVisible();
  });

  it("hydrates saved selected rows through bounded explicit IDs after reopening", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("?search=") ? page([extra]) : url.includes("?product_ids=") ? [extra] : [loaded]);
    const first = open();
    await screen.findByText(loaded.product_name);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "source" } });
    await screen.findByText(extra.product_name);
    fireEvent.change(screen.getAllByRole("spinbutton")[1], { target: { value: "5" } });
    await waitFor(() => expect(localStorage.getItem(Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)!).find((key) => key.includes(":draft:"))!)).toContain('"900":"5"'));
    first.unmount(); fake.fetch.mockClear();
    open();
    await screen.findByText(extra.product_name);
    await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.includes("search=&"))).toBe(true));
    expect(fake.fetch.mock.calls.map(([url]) => url)).toEqual(["/dispatch/route/9/live_inventory", "/dispatch/route/9/live_inventory?product_ids=900", "/dispatch/route/9/live_inventory?search=&limit=80"]);
    expect(screen.getAllByRole("spinbutton")[1]).toHaveValue(5);
  });

  it("shows initial empty/error states and keeps loaded rows usable after a search failure", async () => {
    fake.fetch.mockRejectedValueOnce({ status: 503 });
    const first = open();
    expect(await screen.findByRole("alert")).toHaveTextContent("An unexpected server error occurred.");
    expect(screen.getByRole("button", { name: "Review changes" })).toBeDisabled();
    fake.fetch.mockImplementation(async (url: string) => url.includes("?search=") ? page([]) : []);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No current custody or pending products. Search to add a source warehouse product.")).toBeVisible();
    first.unmount(); fake.fetch.mockResolvedValue([loaded]);
    open();
    await screen.findByText(loaded.product_name);
    fake.fetch.mockRejectedValue({ status: 503 });
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "source" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("An unexpected server error occurred.");
    expect(screen.getByRole("spinbutton")).not.toBeDisabled();
  });

  it("rejects oversized server pages instead of keeping a whole catalog", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("?")
      ? page(Array.from({ length: 81 }, (_, i) => ({ ...extra, product_id: String(900 + i) }))) : [loaded]);
    open();
    await screen.findByText(loaded.product_name);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "source" } });
    await screen.findByRole("alert");
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
  });

  it.each(["en", "ar"] as const)("keeps a physically scoped unsent draft when Warehouse changes in %s; never submits old stock", async (language) => {
    await setAppLanguage(language);
    let changedWarehouse = false;
    let finishOld: (value: unknown) => void = () => {};
    fake.fetch.mockImplementation(async (url: string) => {
      if (url.endsWith("live_inventory")) return [loaded];
      if (url.includes("?product_ids=")) {
        // The strict canonical detail endpoint returns a bare item array, not
        // the paginated discovery wrapper. It is required for saved drafts.
        expect(url).toContain("product_ids=900");
        return [extra];
      }
      if (url.includes("search=old")) return new Promise((resolve) => { finishOld = resolve; });
      return page(changedWarehouse ? [{ ...extra, product_id: "901", product_name: "New source stock" }] : [extra]);
    });
    const oldRoute = { ...route, sourceWarehouseId: "21" };
    const newRoute = { ...route, sourceWarehouseId: "22" };
    const onClose = vi.fn();
    const view = render(<AdjustInventoryModal isOpen onClose={onClose} route={oldRoute} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    await screen.findByText(extra.product_name);
    await waitFor(() => expect(screen.getAllByRole("spinbutton")[0]).not.toBeDisabled());
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "-5" } });
    fireEvent.change(screen.getAllByRole("spinbutton")[1], { target: { value: "5" } });
    fireEvent.change(screen.getByRole("textbox", { name: i18n.t("dispatchAdjustLoad.search") }), { target: { value: "old" } });
    await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.includes("search=old"))).toBe(true));
    changedWarehouse = true;
    view.rerender(<AdjustInventoryModal isOpen onClose={onClose} route={newRoute} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    const prompt = await screen.findByRole("alertdialog", { name: i18n.t("dispatchAdjustLoad.contextChangedTitle") });
    expect(prompt).toBeVisible();
    fireEvent.click(within(prompt).getByRole("button", { name: i18n.t("dispatchAdjustLoad.reviewPrevious") }));
    expect(within(prompt).getByText("521: -5")).toBeVisible();
    expect(within(prompt).getByText("900: 5")).toBeVisible();
    expect(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.review") })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: i18n.t("dispatchAdjustLoad.search") })).toHaveValue("");
    await screen.findByText("New source stock");
    await act(async () => finishOld(page([extra])));
    expect(screen.queryByText(extra.product_name)).not.toBeInTheDocument();
    fireEvent.click(within(prompt).getByRole("button", { name: i18n.t("dispatchAdjustLoad.keepPrevious") }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getAllByRole("spinbutton")[0]).toHaveValue(null);
    expect(fake.fetch.mock.calls.some(([url]) => url.endsWith("adjust_inventory"))).toBe(false);
    changedWarehouse = false;
    view.rerender(<AdjustInventoryModal isOpen onClose={onClose} route={oldRoute} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    await screen.findByText(extra.product_name);
    await waitFor(() => expect(screen.getAllByRole("spinbutton")[0]).toHaveValue(-5));
    expect(fake.fetch.mock.calls.some(([url]) => url.includes("product_ids=900"))).toBe(true);
    expect(screen.getAllByRole("spinbutton")[1]).toHaveValue(5);
    view.unmount();
    render(<AdjustInventoryModal isOpen onClose={onClose} route={oldRoute} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    await waitFor(() => expect(screen.getAllByRole("spinbutton")[0]).toHaveValue(-5));
  });

  it.each(["en", "ar"] as const)("asks explicitly on cancel; keep and discard are separate in %s/mobile", async (language) => {
    await setAppLanguage(language);
    window.innerWidth = 390;
    fake.fetch.mockImplementation(async (url: string) => url.includes("?") ? page([]) : [loaded]);
    const close = vi.fn();
    const props = { isOpen: true, onClose: close, route, onSuccess: vi.fn(), companyId: 1, principalId: 3 };
    const first = render(<AdjustInventoryModal {...props} />);
    await screen.findByRole("spinbutton");
    await waitFor(() => expect(screen.getByRole("spinbutton")).not.toBeDisabled());
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: i18n.t("common.cancel") }));
    const prompt = screen.getByRole("alertdialog", { name: i18n.t("dispatchAdjustLoad.closeTitle") });
    expect(prompt).toBeVisible();
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(within(prompt).getByRole("button", { name: i18n.t("dispatchAdjustLoad.continueEditing") }));
    expect(screen.getByRole("spinbutton")).toHaveValue(5);
    fireEvent.click(screen.getByRole("button", { name: i18n.t("common.cancel") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.keepAndClose") }));
    expect(close).toHaveBeenCalledOnce();
    first.unmount();
    const second = render(<AdjustInventoryModal {...props} />);
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(5));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("common.cancel") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.discardAndClose") }));
    expect(close).toHaveBeenCalledTimes(2);
    second.unmount();
    render(<AdjustInventoryModal {...props} />);
    await waitFor(() => expect(screen.getByRole("spinbutton")).not.toBeDisabled());
    expect(screen.getByRole("spinbutton")).toHaveValue(null);
    expect(fake.fetch.mock.calls.every(([, options]) => options?.method !== "PUT")).toBe(true);
    window.innerWidth = 1024;
  });

  it("migrates a pre-fix legacy unsent draft into the original physical custody without losing it", async () => {
    const legacy = durableScope(1, 3, "dispatch-adjust-base", "9");
    localStorage.setItem(`${legacy}:draft`, JSON.stringify({ "521": "-5" }));
    localStorage.setItem(`${legacy}:draft-context`, JSON.stringify(["9", "17", "21"]));
    fake.fetch.mockImplementation(async (url: string) => url.includes("?") ? page([]) : [loaded]);
    const initial = render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={{ ...route, sourceWarehouseId: "22" }}
      onSuccess={vi.fn()} companyId={1} principalId={3} />);
    const prompt = await screen.findByRole("alertdialog", { name: i18n.t("dispatchAdjustLoad.contextChangedTitle") });
    fireEvent.click(within(prompt).getByRole("button", { name: i18n.t("dispatchAdjustLoad.reviewPrevious") }));
    expect(within(prompt).getByText("521: -5")).toBeVisible();
    fireEvent.click(within(prompt).getByRole("button", { name: i18n.t("dispatchAdjustLoad.keepPrevious") }));
    expect(screen.getByRole("spinbutton")).toHaveValue(null);
    expect(localStorage.getItem(`${legacy}:draft`)).toBeNull();
    initial.unmount();
    render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={{ ...route, sourceWarehouseId: "21" }}
      onSuccess={vi.fn()} companyId={1} principalId={3} />);
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(-5));
    expect(fake.fetch.mock.calls.some(([url]) => url.endsWith("adjust_inventory"))).toBe(false);
  });

  it("quarantines prior draft details when company or principal changes", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("?") ? page([]) : [loaded]);
    const oldProps = { isOpen: true, onClose: vi.fn(), route, onSuccess: vi.fn(), companyId: 1, principalId: 3 };
    const first = render(<AdjustInventoryModal {...oldProps} />);
    await screen.findByRole("spinbutton");
    await waitFor(() => expect(screen.getByRole("spinbutton")).not.toBeDisabled());
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5" } });
    first.rerender(<AdjustInventoryModal {...oldProps} companyId={2} principalId={4} />);
    const prompt = await screen.findByRole("alertdialog", { name: i18n.t("dispatchAdjustLoad.contextChangedTitle") });
    expect(within(prompt).queryByRole("button", { name: i18n.t("dispatchAdjustLoad.reviewPrevious") })).toBeNull();
    expect(within(prompt).queryByRole("button", { name: i18n.t("dispatchAdjustLoad.discardPrevious") })).toBeNull();
    expect(within(prompt).queryByText("701: 5")).toBeNull();
    fireEvent.click(within(prompt).getByRole("button", { name: i18n.t("dispatchAdjustLoad.keepPrevious") }));
    expect(screen.getByRole("spinbutton")).toHaveValue(null);
    expect(fake.fetch.mock.calls.some(([url]) => url.endsWith("adjust_inventory"))).toBe(false);
    first.rerender(<AdjustInventoryModal {...oldProps} />);
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(5));
  });

  it("cannot carry searched rows or drafts into another route", async () => {
    fake.fetch.mockImplementation(async (url: string) => url.includes("/10/") ? url.includes("?") ? page([])
      : [{ ...loaded, product_id: "522", product_name: "Other route custody" }] : url.includes("?") ? page([extra]) : [loaded]);
    const view = open();
    await screen.findByText(loaded.product_name);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "source" } });
    await screen.findByText(extra.product_name);
    fireEvent.change(screen.getAllByRole("spinbutton")[1], { target: { value: "5" } });
    view.rerender(<AdjustInventoryModal isOpen onClose={vi.fn()} route={{ ...route, id: "10" }} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    expect(await screen.findByRole("alertdialog", { name: i18n.t("dispatchAdjustLoad.contextChangedTitle") })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("dispatchAdjustLoad.keepPrevious") }));
    await screen.findByText("Other route custody");
    expect(screen.queryByText(extra.product_name)).not.toBeInTheDocument();
    expect(screen.getByRole("spinbutton")).toHaveValue(null);
    await waitFor(() => expect(fake.fetch.mock.calls.filter(([url]) => url.includes("/10/"))).toHaveLength(2));
    expect(fake.fetch.mock.calls.filter(([url]) => url.includes("/10/")).map(([url]) => url)).toEqual(["/dispatch/route/10/live_inventory", "/dispatch/route/10/live_inventory?search=&limit=80"]);
  });
});

describe("Creation-time radar contracts", () => {
  const legacy = { ...inventory, transfer_id: 81, product_name: "Historical", delta_cartons: 2, delta_packs: 3,
    signed_base_quantity: "19", status: "pending", created_at: null, batch_id: "legacy", can_force_cancel: true };
  it("keeps old carton/piece meaning despite current canonical PACK metadata", () => {
    const [parsed] = parseRouteTransfers([legacy]);
    expect(parsed.quantity_contract).toBeUndefined();
    expect(parsed).not.toHaveProperty("signed_base_quantity");
    expect(parsed).not.toHaveProperty("display_uom_name");
    expect(formatTransferQuantity(parsed)).toBe("+2 cartons, +3 pieces");
    expect(formatTransferQuantity(parseRouteTransfers([{ ...legacy, display_factor_to_base: "4", display_uom_name: "NEW PACK" }])[0]))
      .toBe("+2 cartons, +3 pieces");
  });
  it("uses the matching contract for direction", () => {
    expect(transferIsAddition(parseRouteTransfers([{ ...legacy, delta_cartons: -2, delta_packs: -3, signed_base_quantity: "8" }])[0])).toBe(false);
    expect(transferIsAddition(parseRouteTransfers([{ ...legacy, quantity_contract: "CANONICAL_BASE_V1", signed_base_quantity: "-5" }])[0])).toBe(false);
    expect(transferIsAddition(parseRouteTransfers([{ ...legacy, quantity_contract: "CANONICAL_BASE_V1", delta_cartons: -2, signed_base_quantity: "8" }])[0])).toBe(true);
  });
  it.each([
    { delta_cartons: "2" }, { delta_packs: 0.5 }, { delta_cartons: 0, delta_packs: 0 },
    { quantity_contract: "UNKNOWN" }, { quantity_contract: "CANONICAL_BASE_V1", signed_base_quantity: null },
    { quantity_contract: "CANONICAL_BASE_V1", quantity_step: null },
  ])("rejects malformed discriminated evidence %j", (invalid) => {
    expect(() => parseRouteTransfers([{ ...legacy, ...invalid }])).toThrow();
  });
  it.each([
    [null, "19", "+2 cartons, +3 pieces"],
    ["CANONICAL_BASE_V1", "8", "+1 PACK"],
    ["CANONICAL_BASE_V1", "25", "+3 PACK + 1 unit"],
  ])("list and force-cancel share the %s quantity formatter", async (marker, quantity, expected) => {
    const raw = { ...legacy, quantity_contract: marker, signed_base_quantity: quantity };
    fake.fetch.mockResolvedValue([raw]);
    render(<TransfersRadarModal isOpen onClose={vi.fn()} route={route} />);
    const output = String(expected).replace("unit", i18n.t("uom.EACH"));
    expect(await screen.findByText(output)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(within(screen.getByRole("dialog", { name: "Cancel pending transfer" })).getByText(output)).toBeInTheDocument();
  });
});

describe("Durable adjustment command", () => {
  const body = { deltas: [{ product_id: 701, delta_base: "5" }] };
  it("does not carry a previous route's busy state or completion into the new route", async () => {
    let finish: (value: { mode: string }) => void;
    fake.fetch.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const view = renderHook(({ routeId }) => useAdjustLoadCommand(routeId, 1, 3), { initialProps: { routeId: "9" } });
    await waitFor(() => expect(view.result.current.ready).toBe(true));
    let running: Promise<string | null>;
    act(() => { running = view.result.current.execute(body); });
    await waitFor(() => expect(fake.fetch).toHaveBeenCalledOnce());
    expect(view.result.current.busy).toBe(true);
    view.rerender({ routeId: "10" });
    await waitFor(() => expect(view.result.current.ready).toBe(true));
    expect(view.result.current.busy).toBe(false);
    expect(view.result.current.pending).toBeNull();
    await act(async () => { finish!({ mode: "DIRECT" }); expect(await running!).toBeNull(); });
    expect(view.result.current.pending).toBeNull();
    expect(fake.fetch).toHaveBeenCalledOnce();
  });

  it("retains an ambiguous body/UUID across refresh and prevents a conflicting new command", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE", status: 0 }));
    const first = renderHook(() => useAdjustLoadCommand("9", 1, 3));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    await act(async () => { await expect(first.result.current.execute(body)).rejects.toBeDefined(); });
    expect(first.result.current.recoveryRequired).toBe(true);
    const firstWire = fake.fetch.mock.calls[0][1].body;
    first.unmount();
    const resumed = renderHook(() => useAdjustLoadCommand("9", 1, 3));
    await waitFor(() => expect(resumed.result.current.pending).not.toBeNull());
    expect(resumed.result.current.recoveryRequired).toBe(true);
    expect(fake.fetch).toHaveBeenCalledOnce(); // No automatic replay on mount.
    await act(async () => { await expect(resumed.result.current.execute({ deltas: [{ product_id: 701, delta_base: "8" }] }))
      .rejects.toMatchObject({ code: "DURABLE_OPERATION_PENDING" }); });
    expect(fake.fetch).toHaveBeenCalledOnce();
    fake.fetch.mockResolvedValue({ mode: "HANDSHAKE" });
    await act(async () => { expect(await resumed.result.current.execute()).toBe("HANDSHAKE"); });
    expect(fake.fetch.mock.calls[1][1].body).toBe(firstWire);
    expect(resumed.result.current.pending).toBeNull();
    expect(resumed.result.current.recoveryRequired).toBe(false);
  });

  it("does not replay a pending durable command after the same route moves to another vehicle or Warehouse", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE", status: 0 }));
    const first = renderHook(({ physical }) => useAdjustLoadCommand("9", 1, 3, physical),
      { initialProps: { physical: '["9","17","21",null,1]' } });
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    await act(async () => { await expect(first.result.current.execute(body)).rejects.toBeDefined(); });
    expect(first.result.current.recoveryRequired).toBe(true);
    const originalScope = first.result.current.scope;
    const originalWire = fake.fetch.mock.calls[0][1].body;
    first.rerender({ physical: '["9","18","22",null,2]' });
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    expect(first.result.current.scope).not.toBe(originalScope);
    expect(first.result.current.recoveryRequired).toBe(false);
    expect(first.result.current.pending).toBeNull();
    expect(localStorage.getItem(originalScope!)).not.toBeNull();
    expect(fake.fetch).toHaveBeenCalledOnce();
    first.rerender({ physical: '["9","17","21",null,1]' });
    await waitFor(() => expect(first.result.current.recoveryRequired).toBe(true));
    fake.fetch.mockResolvedValue({ mode: "DIRECT" });
    await act(async () => { expect(await first.result.current.execute()).toBe("DIRECT"); });
    expect(fake.fetch.mock.calls[1][1].body).toBe(originalWire);
  });

  it("does not hide or replay an unresolved legacy route-only durable request during physical-context cutover", async () => {
    const legacy = durableScope(1, 3, "dispatch-adjust-base", "9");
    await getOrCreateDurableCommand(legacy, body);
    const view = renderHook(() => useAdjustLoadCommand("9", 1, 3, '["9","17","21",null,1]'));
    await waitFor(() => expect(view.result.current.recoveryError).toMatchObject({
      code: "DISPATCH_LEGACY_RECOVERY_REQUIRED",
    }));
    expect(view.result.current.recoveryRequired).toBe(true);
    expect(view.result.current.ready).toBe(false);
    expect(fake.fetch).not.toHaveBeenCalled();
    await act(async () => { await expect(view.result.current.execute(body)).rejects.toBeDefined(); });
    expect(localStorage.getItem(legacy)).not.toBeNull();
    expect(fake.fetch).not.toHaveBeenCalled();
  });

  it.each(["en", "ar"] as const)("explicit legacy recovery in %s verifies the original UUID without replay or lost evidence", async (language) => {
    await setAppLanguage(language);
    const legacy = durableScope(1, 3, "dispatch-adjust-base", "9");
    const original = await getOrCreateDurableCommand(legacy, body);
    const physical = '["9","17","21",null,1]';
    const view = renderHook(() => useAdjustLoadCommand("9", 1, 3, physical));
    await waitFor(() => expect(view.result.current.legacyPending?.requestId).toBe(original.requestId));
    expect(view.result.current.ready).toBe(false);
    fake.fetch.mockResolvedValueOnce({ state: "NOT_CONFIRMED", request_id: original.requestId });
    await act(async () => { await view.result.current.inspectLegacy(); });
    expect(view.result.current.legacyOutcome).toBe("NOT_CONFIRMED");
    act(() => view.result.current.acknowledgeCommittedLegacy());
    expect(localStorage.getItem(legacy)).not.toBeNull();
    expect(view.result.current.ready).toBe(false);
    fake.fetch.mockResolvedValueOnce({ state: "COMMITTED", request_id: original.requestId, response: { mode: "DIRECT" } });
    await act(async () => { await view.result.current.inspectLegacy(); });
    expect(view.result.current.legacyOutcome).toBe("COMMITTED");
    const requests = fake.fetch.mock.calls;
    expect(requests).toHaveLength(2);
    expect(requests.every(([url, options]) => url === "/dispatch/route/9/adjust_inventory/recovery" &&
      options.method === "POST" && JSON.parse(options.body).request_id === original.requestId &&
      JSON.parse(options.body).deltas[0].delta_base === "5")).toBe(true);
    act(() => view.result.current.acknowledgeCommittedLegacy());
    expect(localStorage.getItem(legacy)).toBeNull();
    expect(view.result.current.ready).toBe(true);
    expect(fake.fetch).toHaveBeenCalledTimes(2); // Read-only; no Adjust Load POST/PUT replay
  });

  it.each(["en", "ar"] as const)("permanently cancels only a server-verified NOT_CONFIRMED legacy request in %s", async (language) => {
    await setAppLanguage(language);
    const legacy = durableScope(1, 3, "dispatch-adjust-base", "9");
    const original = await getOrCreateDurableCommand(legacy, body);
    const view = renderHook(() => useAdjustLoadCommand("9", 1, 3, '["9","17","21",null,1]'));
    await waitFor(() => expect(view.result.current.legacyPending?.requestId).toBe(original.requestId));

    fake.fetch.mockResolvedValueOnce({ state: "NOT_CONFIRMED", request_id: original.requestId });
    await act(async () => { await view.result.current.inspectLegacy(); });
    expect(view.result.current.legacyOutcome).toBe("NOT_CONFIRMED");

    fake.fetch.mockResolvedValueOnce({ state: "CANCELLED", request_id: original.requestId });
    await act(async () => { await view.result.current.cancelLegacy(); });
    expect(localStorage.getItem(legacy)).toBeNull();
    expect(view.result.current.legacyPending).toBeNull();
    expect(view.result.current.ready).toBe(true);
    expect(fake.fetch.mock.calls.map(([url]) => url)).toEqual([
      "/dispatch/route/9/adjust_inventory/recovery",
      "/dispatch/route/9/adjust_inventory/recovery/cancel",
    ]);
  });

  it("keeps the original legacy command when cancellation response is lost, then safely retries the same cancellation", async () => {
    const legacy = durableScope(1, 3, "dispatch-adjust-base", "9");
    const original = await getOrCreateDurableCommand(legacy, body);
    const view = renderHook(() => useAdjustLoadCommand("9", 1, 3, '["9","17","21",null,1]'));
    await waitFor(() => expect(view.result.current.legacyPending).not.toBeNull());

    fake.fetch.mockResolvedValueOnce({ state: "NOT_CONFIRMED", request_id: original.requestId });
    await act(async () => { await view.result.current.inspectLegacy(); });
    fake.fetch.mockRejectedValueOnce(Object.assign(new Error("lost"), { code: "NETWORK_UNAVAILABLE", status: 0 }));
    await act(async () => { await expect(view.result.current.cancelLegacy()).rejects.toBeDefined(); });
    expect(localStorage.getItem(legacy)).toContain(original.requestId);
    expect(view.result.current.legacyPending?.requestId).toBe(original.requestId);

    fake.fetch.mockResolvedValueOnce({ state: "CANCELLED", request_id: original.requestId });
    await act(async () => { await view.result.current.cancelLegacy(); });
    expect(localStorage.getItem(legacy)).toBeNull();
    expect(view.result.current.ready).toBe(true);
  });

  it("does not reuse a durable command after an ABA assignment returns to the same visible vehicle and warehouse", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE", status: 0 }));
    const view = renderHook(({ physical }) => useAdjustLoadCommand("9", 1, 3, physical),
      { initialProps: { physical: '["9","17","21",null,1]' } });
    await waitFor(() => expect(view.result.current.ready).toBe(true));
    await act(async () => { await expect(view.result.current.execute(body)).rejects.toBeDefined(); });
    const originalScope = view.result.current.scope;
    view.rerender({ physical: '["9","17","21",null,3]' });
    await waitFor(() => expect(view.result.current.ready).toBe(true));
    expect(view.result.current.scope).not.toBe(originalScope);
    expect(view.result.current.pending).toBeNull();
    expect(localStorage.getItem(originalScope!)).not.toBeNull();
    expect(fake.fetch).toHaveBeenCalledOnce();
  });

  it("rejects a mismatched legacy UUID/result and preserves the original command", async () => {
    const legacy = durableScope(1, 3, "dispatch-adjust-base", "9");
    const original = await getOrCreateDurableCommand(legacy, body);
    const view = renderHook(() => useAdjustLoadCommand("9", 1, 3, '["9","17","21",null,1]'));
    await waitFor(() => expect(view.result.current.legacyPending).not.toBeNull());
    fake.fetch.mockResolvedValue({ state: "COMMITTED", request_id: crypto.randomUUID(), response: { mode: "DIRECT" } });
    await act(async () => { await expect(view.result.current.inspectLegacy()).rejects.toMatchObject({
      code: "DISPATCH_RECOVERY_RESPONSE_INVALID",
    }); });
    expect(view.result.current.legacyOutcome).toBeNull();
    expect(localStorage.getItem(legacy)).toContain(original.requestId);
    expect(view.result.current.ready).toBe(false);
  });

  it("clears only confirmed 4xx rejection and keeps drafts scoped by actor", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { status: 409, code: "DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED" }));
    const view = renderHook(() => useAdjustLoadCommand("9", 1, 3));
    await waitFor(() => expect(view.result.current.ready).toBe(true));
    await act(async () => { await expect(view.result.current.execute(body)).rejects.toBeDefined(); });
    expect(view.result.current.pending).toBeNull();
    expect(localStorage.getItem(view.result.current.scope!)).toBeNull();
    fake.online = false;
    view.rerender();
    await act(async () => { await expect(view.result.current.execute(body)).rejects.toBeDefined(); });
    expect(fake.fetch).toHaveBeenCalledOnce();
    const other = renderHook(() => useAdjustLoadCommand("9", 1, 4));
    await waitFor(() => expect(other.result.current.ready).toBe(true));
    expect(other.result.current.scope).not.toBe(view.result.current.scope);
  });
});
