import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import type { ReactNode } from "react";
import i18n, { setAppLanguage } from "@/i18n";
import type { PendingRoute } from "@/types/dispatch";
import { AdjustInventoryModal } from "@/components/dispatch/AdjustInventoryModal";
import { TransfersRadarModal } from "@/components/dispatch/TransfersRadarModal";
import { adjustmentReview, buildAdjustmentPayload, parseAdjustLoadInventory } from "@/features/dispatch/adjustLoad";
import { parseRouteTransfers, formatTransferQuantity } from "@/features/dispatch/routeTransfers";
import { formatRouteLoadQuantity } from "@/features/dispatch/routeLoadUom";
import { useAdjustLoadCommand } from "@/features/dispatch/useAdjustLoadCommand";

const fake = vi.hoisted(() => ({ fetch: vi.fn(), online: true, error: vi.fn(), success: vi.fn(), info: vi.fn() }));
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
const route: PendingRoute = { id: "9", zoneId: "1", zoneName: "Zone", driverId: "31", driverName: "Rep", vehicleId: "17",
  shopsRemaining: 2, status: "active", sessionEnded: false, sessionBound: false, can_execute: true, commercial_context: null };

beforeEach(async () => {
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  localStorage.clear(); fake.fetch.mockReset(); fake.online = true;
  fake.error.mockClear(); fake.success.mockClear(); fake.info.mockClear();
  await setAppLanguage("en");
});

describe("Canonical Adjust Load quantities and radar", () => {
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

  it.each([["8", "+1 PACK"], ["5", "+5 EACH"], ["-5", "−5 EACH"]])("radar presents exact signed base %s as %s", (value, expected) => {
    const [transfer] = parseRouteTransfers([{ ...inventory, transfer_id: 1, signed_base_quantity: value,
      status: "pending", created_at: null, batch_id: "b", can_force_cancel: true }]);
    expect(formatTransferQuantity(transfer)).toBe(expected);
    expect(formatTransferQuantity(transfer)).not.toMatch(/carton|كرتونة/);
  });

  it("does not reconstruct a missing canonical radar quantity from legacy fields", () => {
    expect(() => parseRouteTransfers([{ ...inventory, transfer_id: 1, status: "pending",
      created_at: null, batch_id: "b", can_force_cancel: true }])).toThrow();
  });
});

describe("Adjust Load operator workflow", () => {
  it.each(["en", "ar"] as const)("renders radar from canonical UOM evidence in %s", async (language) => {
    await setAppLanguage(language);
    fake.fetch.mockResolvedValue(["8", "5", "-5"].map((quantity, index) => ({ ...inventory,
      transfer_id: index + 1, signed_base_quantity: quantity, status: "pending", created_at: null,
      batch_id: "b", can_force_cancel: false, delta_cartons: 999, delta_packs: 999,
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
    fake.fetch.mockImplementation(async (url: string) => url.endsWith("live_inventory") ? [inventory] : { mode: "DIRECT" });
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

  it("keeps pending net visible and zero adjustment sends no mutation", async () => {
    fake.fetch.mockResolvedValue([{ ...inventory, pending_base_quantity: "8" }]);
    render(<AdjustInventoryModal isOpen onClose={vi.fn()} route={{ ...route, sessionBound: true }} onSuccess={vi.fn()} companyId={1} principalId={3} />);
    await screen.findByRole("spinbutton");
    await waitFor(() => expect(screen.getByRole("button", { name: "Review changes" })).not.toBeDisabled());
    expect(screen.getByText(/Net pending handshakes/)).toHaveTextContent("1 PACK");
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(fake.info).toHaveBeenCalledWith(i18n.t("dispatchAdjustLoad.empty"));
    expect(fake.fetch).toHaveBeenCalledOnce();
  });
});

describe("Durable adjustment command", () => {
  const body = { deltas: [{ product_id: 701, delta_base: "5" }] };
  it("retains an ambiguous body/UUID across refresh and prevents a conflicting new command", async () => {
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE", status: 0 }));
    const first = renderHook(() => useAdjustLoadCommand("9", 1, 3));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    await act(async () => { await expect(first.result.current.execute(body)).rejects.toBeDefined(); });
    const firstWire = fake.fetch.mock.calls[0][1].body;
    first.unmount();
    const resumed = renderHook(() => useAdjustLoadCommand("9", 1, 3));
    await waitFor(() => expect(resumed.result.current.pending).not.toBeNull());
    expect(fake.fetch).toHaveBeenCalledOnce(); // No automatic replay on mount.
    await act(async () => { await expect(resumed.result.current.execute({ deltas: [{ product_id: 701, delta_base: "8" }] }))
      .rejects.toMatchObject({ code: "DURABLE_OPERATION_PENDING" }); });
    expect(fake.fetch).toHaveBeenCalledOnce();
    fake.fetch.mockResolvedValue({ mode: "HANDSHAKE" });
    await act(async () => { expect(await resumed.result.current.execute()).toBe("HANDSHAKE"); });
    expect(fake.fetch.mock.calls[1][1].body).toBe(firstWire);
    expect(resumed.result.current.pending).toBeNull();
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
