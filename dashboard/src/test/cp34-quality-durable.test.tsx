import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { parseInventoryCapabilities } from "@/hooks/useInventoryAccess";
import { useBatchTerminalAction } from "@/pages/inventory/batches/useBatchTerminalAction";
import { useProductQualityCommands } from "@/features/inventory/quality/useProductQualityCommands";
import { durableScope, readDurableCommand, getOrCreateDurableCommand } from "@/lib/durableOperations";
import { parseBatchStockSources } from "@/pages/inventory/batches/batchStockSourcesContract";
import { batchFocusPayload, batchSource } from "./fixtures/batchFocus";

const fake = vi.hoisted(() => ({
  fetch: vi.fn(), online: true,
  data: { company_id: 1, principal_id: 101, backoffice_user_id: 202, driver_id: 7 } as Record<string, number>,
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/hooks/useNetworkStatus", () => ({ useNetworkStatus: () => fake.online }));
vi.mock("@/hooks/useInventoryAccess", async (original) => ({
  ...await original<typeof import("@/hooks/useInventoryAccess")>(),
  useInventoryAccess: () => ({ data: fake.data, can: () => true }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const batch = parseBatchStockSources(batchFocusPayload([batchSource(11, "A1")])).batch;
const disposal = {
  action: "CONFIRM_DISPOSAL" as const, sourceLocationId: 11,
  sourceStatus: "DISPOSAL_PENDING" as const, quantity: "0.123456", reason: "Confirmed damage",
};
const terminalResult = {
  event_type: "INVENTORY_FINAL_DISPOSAL_CONFIRMED", movement_ids: [501],
  disposed_quantity: "0.123456", remaining_quantity: "7.876544", origin_transfer_header_ids: [71],
};
const terminalScope = () => durableScope(1, 202, "batch-terminal-quality-v1",
  [batch.batch_id, 11, "DISPOSAL_PENDING", "CONFIRM_DISPOSAL"].join(":"));
const mountTerminal = (onSucceeded = vi.fn()) => renderHook(() => useBatchTerminalAction({
  batch, productVariantId: 118, baseUomCode: "EACH", onSucceeded,
}));
const networkError = () => Object.assign(new Error(), { code: "NETWORK_UNAVAILABLE" });

beforeEach(() => {
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: webcrypto });
  localStorage.clear(); fake.fetch.mockReset(); fake.online = true;
  fake.data = { company_id: 1, principal_id: 101, backoffice_user_id: 202, driver_id: 7 };
});
afterEach(cleanup);

describe("CP3.4 canonical terminal command recovery", () => {
  it("accepts the real access contract with independent IDs and rejects Driver-only identity", () => {
    const canonical = { ...fake.data, is_company_owner: false, location_id: null,
      permissions: [], any_permissions: [], location_permissions: [] };
    expect(parseInventoryCapabilities(canonical)).toMatchObject({
      company_id: 1, principal_id: 101, backoffice_user_id: 202,
    });
    expect(() => parseInventoryCapabilities({ ...canonical, backoffice_user_id: undefined }))
      .toThrow("INVENTORY_ACCESS_RESPONSE_INVALID");
  });

  it("never falls back to Driver identity or sends while offline", async () => {
    delete fake.data.backoffice_user_id;
    const hook = mountTerminal();
    await act(async () => { expect(await hook.result.current.run(disposal)).toBe(false); });
    expect(fake.fetch).not.toHaveBeenCalled();
    fake.data.backoffice_user_id = 202; fake.online = false; hook.rerender();
    await act(async () => { expect(await hook.result.current.run(disposal)).toBe(false); });
    expect(fake.fetch).not.toHaveBeenCalled();
  });

  it("retains exact payload and request identity after loss, reload and changed-input attempt", async () => {
    fake.fetch.mockRejectedValue(networkError());
    const first = mountTerminal();
    await act(async () => { expect(await first.result.current.run(disposal)).toBe(false); });
    const sent = JSON.parse(fake.fetch.mock.calls[0][1].body);
    expect(sent.quantity).toBe("0.123456");
    expect(await readDurableCommand(terminalScope())).toMatchObject({ requestId: sent.request_id });
    expect(await readDurableCommand(durableScope(1, 7, "batch-terminal-quality-v1",
      [batch.batch_id, 11, "DISPOSAL_PENDING", "CONFIRM_DISPOSAL"].join(":")))).toBeNull();
    first.unmount();
    const complete = vi.fn();
    const resumed = mountTerminal(complete);
    await act(async () => { expect(await resumed.result.current.run({ ...disposal, quantity: "1" })).toBe(false); });
    expect(fake.fetch).toHaveBeenCalledTimes(1);
    fake.fetch.mockResolvedValue(terminalResult);
    await act(async () => { expect(await resumed.result.current.run(disposal)).toMatchObject({ completed_quantity: "0.123456" }); });
    expect(JSON.parse(fake.fetch.mock.calls[1][1].body)).toEqual(sent);
    expect(complete).toHaveBeenCalledOnce();
    expect(await readDurableCommand(terminalScope())).toBeNull();
  });

  it("coalesces same-render double submission before asynchronous durable hashing", async () => {
    fake.fetch.mockResolvedValue(terminalResult);
    const complete = vi.fn(); const hook = mountTerminal(complete);
    await act(async () => { await Promise.all([hook.result.current.run(disposal), hook.result.current.run(disposal)]); });
    expect(fake.fetch).toHaveBeenCalledOnce();
    expect(complete).toHaveBeenCalledOnce();
  });

  it("does not cross-replay a stored terminal operation for another company, profile, location or action", async () => {
    await getOrCreateDurableCommand(terminalScope(), { marker: "original" });
    expect(await readDurableCommand(terminalScope())).not.toBeNull();
    for (const [company, actor, target] of [
      [2, 202, [batch.batch_id, 11, "DISPOSAL_PENDING", "CONFIRM_DISPOSAL"].join(":")],
      [1, 303, [batch.batch_id, 11, "DISPOSAL_PENDING", "CONFIRM_DISPOSAL"].join(":")],
      [1, 202, [batch.batch_id, 12, "DISPOSAL_PENDING", "CONFIRM_DISPOSAL"].join(":")],
      [1, 202, [batch.batch_id, 11, "QUARANTINED", "CONFIRM_VENDOR_HANDOVER"].join(":")],
    ] as const) expect(await readDurableCommand(durableScope(company, actor, "batch-terminal-quality-v1", target))).toBeNull();
  });

  it("retains ambiguous 5xx responses and rejects a malformed success without losing recovery identity", async () => {
    const hook = mountTerminal();
    fake.fetch.mockRejectedValue(Object.assign(new Error(), { code: "DISPOSAL_PENDING_STOCK_NOT_FOUND", status: 500 }));
    await act(async () => { await hook.result.current.run(disposal); });
    const stored = await readDurableCommand(terminalScope());
    expect(stored).not.toBeNull();
    fake.fetch.mockResolvedValue({ event_type: "INVENTORY_FINAL_DISPOSAL_CONFIRMED" });
    await act(async () => { await hook.result.current.run(disposal); });
    expect((await readDurableCommand(terminalScope()))?.requestId).toBe(stored?.requestId);
  });
});

describe("CP3.4 whole-product canonical recovery", () => {
  it("does not discover pending commands through a legacy Driver scope", async () => {
    await getOrCreateDurableCommand(durableScope(1, 7, "whole-product-quality-resolve-v3", 118),
      { action: "DISPOSE", reason: "Issue", post_resolution_hold: "NONE" });
    const hook = renderHook(() => useProductQualityCommands({ productVariantId: 118, onSucceeded: vi.fn() }));
    await waitFor(() => expect(hook.result.current.recoveryReady).toBe(true));
    expect(hook.result.current.pending).toBeNull();
    delete fake.data.backoffice_user_id; hook.rerender();
    await act(async () => { expect(await hook.result.current.resolveAll({
      action: "DISPOSE", reason: "Issue", confirmationPassword: "credential", postResolutionHold: "NONE",
    })).toBe(false); });
    expect(fake.fetch).not.toHaveBeenCalled();
  });
});
