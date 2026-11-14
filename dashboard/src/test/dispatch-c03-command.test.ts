import { describe, expect, it, vi } from "vitest";
import {
  acceptOnce, loadCustody, pendingClear, pendingKey, pendingRead, pendingSave,
  prepareHandoff, statusByRequest, type AuthorizedFetch,
} from "../features/dispatch/custodyRecovery/command";
import { custodyReason } from "../features/dispatch/custodyRecovery/copy";
const fingerprint = "a".repeat(64);
const ready = {
  vehicle_id: 18, vehicle_location_id: 30, context_revision: 1,
  state: "NEEDS_REVIEW", custodian_kind: "UNCONFIRMED",
  stocked: true, stock_snapshot: fingerprint, stock_line_count: 1,
  recovery_action: "CUSTODY_FIRST_ACCEPT",
} as const;
const stock = {
  vehicle_id: 18, context_revision: 1, stock_snapshot: fingerprint,
  stock_lines: [{
    product_name: "Kids Chips", sku: "K-1", batch_number: "LOT-A",
    expiry_date: null, base_uom: "EACH", base_uom_name: "حبة",
    display_uom_name: "باكيت", display_factor_to_base: "8", stock_status: "AVAILABLE",
    on_hand_base: "12", reserved_base: "0",
  }],
};
describe("C03 bounded signed custody client", () => {
  it("verifies actual two-read revision/snapshot agreement", async () => {
    const fetch = vi.fn(async (path: string) =>
      path.endsWith("/readiness") ? ready : stock);
    const ctl = new AbortController();
    const result = await loadCustody(fetch, "18", ctl.signal);
    expect(result.ready.stock_snapshot).toBe(fingerprint);
    expect(result.stock.stock_lines[0].batch_number).toBe("LOT-A");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("fails closed on divergent revision, even if one read succeeds", async () => {
    const fetch = vi.fn(async (path: string) =>
      path.endsWith("/readiness") ? ready : {...stock,context_revision:2});
    await expect(loadCustody(fetch,"18",new AbortController().signal))
      .rejects.toThrow("C03_STOCK_SNAPSHOT_STALE");
  });
  it("never invents a caller-selected quantity or receiver signature", async () => {
    const fetch = vi.fn(async (_:string,init?:RequestInit) => ({
      action: "FIRST_ACCEPT",offer_token:"s".repeat(150),expires_in_seconds:900,
      stock_snapshot:fingerprint,stock_line_count:1,vehicle_location_id:30,
    }));
    const offer = await prepareHandoff(fetch,"18","6",ready,stock);
    expect(offer.action).toBe("FIRST_ACCEPT");
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
      target_driver_id:6,expected_context_revision:1,
      expected_stock_snapshot:fingerprint,
    });
    await expect(prepareHandoff(fetch,"18","0006",ready,stock)).rejects.toThrow();
  });
  it("same UUID and signed proof produce identical retry request", async () => {
    const input:unknown[] = [];
    const fetch:AuthorizedFetch = async (_,init) => {
      input.push(JSON.parse(String(init?.body)));
      return {vehicle_id:18,epoch_id:80,context_revision:2,
        state:"ACCEPTED",replayed:input.length===2,stock_movements:0};
    };
    const uuid="3e41e9bc-73d0-4691-94b8-7cf99bacb5b3",proof="x".repeat(130);
    expect((await acceptOnce(fetch,"18",uuid,proof)).kind).toBe("committed");
    expect((await acceptOnce(fetch,"18",uuid,proof)).kind).toBe("committed");
    expect(input).toEqual([input[0],input[0]]);
  });
  it("does not turn an unknown response or 409 into accepted", async () => {
    const offline:AuthorizedFetch = async () => {throw new Error("Network unavailable");};
    expect((await acceptOnce(offline,"18","id","proof")).kind).toBe("unknown");
    const stale:AuthorizedFetch = async () => {
      throw Object.assign(new Error("Conflict"),{status:409,code:"CUSTODY_REVISION_STALE"});
    };
    expect(await acceptOnce(stale,"18","id","proof")).toEqual({
      kind:"conflict",code:"CUSTODY_REVISION_STALE",
    });
  });
  it("only a non-secret UUID may persist; lookup never guesses acceptance", async () => {
    const key=pendingKey("21:9","18"),uuid="3e41e9bc-73d0-4691-94b8-7cf99bacb5b3";
    pendingSave(key,uuid);
    expect(pendingRead(key)).toBe(uuid);
    const fetch:AuthorizedFetch=async()=>({state:"UNKNOWN"});
    expect((await statusByRequest(fetch,"18",uuid)).state).toBe("UNKNOWN");
    pendingClear(key);
    expect(pendingRead(key)).toBe(null);
  });
  it("provides plain bilingual reason for unknown/other custodian", () => {
    expect(custodyReason("CUSTODY_STOCK_WITHOUT_EPOCH","ar")).toContain("سجل");
    expect(custodyReason("CUSTODY_REQUIRES_REASSIGNMENT","en")).toContain("Another");
  });
});
