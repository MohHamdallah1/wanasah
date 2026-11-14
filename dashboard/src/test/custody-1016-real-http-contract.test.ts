/**
 * #1016 opt-in: real signed PG16 HTTP responses from the one Backend E2E.
 * No invented fixtures. WANASAH_CUSTODY_1016_CAPTURE is outside the repo.
 */
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {describe, expect, it} from "vitest";
import {getCurrentHandoff,sendHandoff,cancelHandoff,approveHandoff,loadCustodyHistory} from
  "@/features/dispatch/custodyRecovery/handoffApi";

const capture=process.env.WANASAH_CUSTODY_1016_CAPTURE ??
  resolve(process.cwd(),"../wa_backend/tests/fixtures/custody_1016_real_pg16_http.json");
const live=JSON.parse(readFileSync(capture,"utf8")) as Record<string,unknown>;
const field=(k:string)=>live?.[k];
type Handoff={handoff_id:number;vehicle_id:number;target_driver_id:number;state:string};

describe("CUSTODY-INT #1016 real PG16 HTTP -> merged Dashboard parser",()=>{
  it("restores real pending/confirmed status and a numeric handoff ID",async()=>{
    const raw=field("manager_pending") as Handoff;
    const current=await getCurrentHandoff(async(path)=>{
      expect(path).toBe("/vehicles/"+raw.vehicle_id+"/custody/handoffs/current");
      return field("manager_reloaded");
    },String(raw.vehicle_id));
    expect(current?.handoff_id).toBe(raw.handoff_id);
    expect(current?.target_driver_id).toBe(raw.target_driver_id);
    expect(current?.state).toBe("CONFIRMED");
    expect(Number.isSafeInteger(current?.handoff_id)).toBe(true);
    expect(current?.recipient_label).toBeTruthy();
  });
  it("uses canonical UUID request body and actual revision/snapshot",async()=>{
    const raw=field("manager_pending") as Handoff;
    const stock=field("manager_stock") as {stock_snapshot:string};
    const ready=field("manager_readiness") as {context_revision:number};
    const id="12345678-1234-4234-8234-123456789abc";
    const sent=await sendHandoff(async(path,init)=>{
      expect(path).toBe("/vehicles/"+raw.vehicle_id+"/custody/handoffs");
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({
        request_id:id,target_driver_id:raw.target_driver_id,
        expected_context_revision:ready.context_revision,
        expected_stock_snapshot:stock.stock_snapshot,
      });
      return field("manager_pending");
    },String(raw.vehicle_id),{
      request_id:id,target_driver_id:raw.target_driver_id,
      expected_context_revision:ready.context_revision,
      expected_stock_snapshot:stock.stock_snapshot,
    });
    expect(sent.state).toBe("PENDING");
    expect(sent.handoff_id).toBe(raw.handoff_id);
  });
  it("recognizes genuine server cancellation and zero-movement committed receipt",async()=>{
    const cancelled=field("manager_cancelled") as Handoff;
    const cancel=await cancelHandoff(async(path)=>{
      expect(path).toBe("/vehicles/"+cancelled.vehicle_id+"/custody/handoffs/"+cancelled.handoff_id+"/cancel");
      return cancelled;
    },String(cancelled.vehicle_id),cancelled.handoff_id,"12345678-1234-4234-8234-123456789abc");
    expect(cancel.state).toBe("CANCELLED");
    const receipt=field("manager_approved") as {vehicle_id:number;handoff_id:number;epoch_id:number};
    const approved=await approveHandoff(async(path)=>{
      expect(path).toContain("/custody/handoffs/"+receipt.handoff_id+"/approve");
      return receipt;
    },String(receipt.vehicle_id),receipt.handoff_id,"12345678-1234-4234-8234-123456789abc");
    expect(approved.state).toBe("ACCEPTED");
    expect(approved.stock_movements).toBe(0);
    expect(approved.epoch_id).toBe(receipt.epoch_id);
  });
  it("reads both historically accepted principals and honest legacy unknown",async()=>{
    const raw=field("manager_history") as {vehicle_id:number;items:Array<unknown>};
    const history=await loadCustodyHistory(async(path)=>{
      expect(path).toBe("/vehicles/"+raw.vehicle_id+"/custody/history?limit=20");
      return raw;
    },String(raw.vehicle_id));
    const accepted=history.filter(r=>r.state==="ACCEPTED");
    expect(accepted).toHaveLength(2);
    expect(accepted[0].recipient_label).not.toBe(accepted[1].recipient_label);
    expect(history.some(r=>r.legacy_unconfirmed && !r.recipient_label)).toBe(true);
    expect(accepted.some(r=>r.ended_at)).toBe(true);
  });
});
