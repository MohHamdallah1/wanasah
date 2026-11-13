import { apiErrorCode, apiErrorStatus } from "@/lib/apiErrors";
import { accepted, lookup, offer, readiness, review, type Readiness, type StockReview } from "./contract";

export type AuthorizedFetch=(path:string,init?:RequestInit)=>Promise<unknown>;
const id=(s:string)=>/^[1-9][0-9]*$/.test(s)&&Number.isSafeInteger(Number(s));
export const validVehicleId=id;
const root=(vehicleId:string)=>{
  if(!id(vehicleId))throw new Error("C03_INVALID_VEHICLE");
  return "/vehicles/"+vehicleId+"/custody";
};
export async function loadCustody(fetch:AuthorizedFetch,vehicleId:string,signal:AbortSignal){
  const [r,s]=await Promise.all([
    fetch(root(vehicleId)+"/readiness",{signal,cache:"no-store"}),
    fetch(root(vehicleId)+"/stock-review",{signal,cache:"no-store"}),
  ]);
  const ready=readiness.parse(r),stock=review.parse(s);
  if(ready.vehicle_id!==Number(vehicleId)||stock.vehicle_id!==ready.vehicle_id||
     ready.context_revision!==stock.context_revision||
     ready.stock_snapshot!==stock.stock_snapshot)throw new Error("C03_STOCK_SNAPSHOT_STALE");
  return {ready,stock};
}
export async function prepareHandoff(fetch:AuthorizedFetch,vehicleId:string,
  driverId:string,ready:Readiness,stock:StockReview){
  if(!id(driverId)||stock.stock_snapshot!==ready.stock_snapshot||
    stock.context_revision!==ready.context_revision)throw new Error("C03_STOCK_SNAPSHOT_STALE");
  const response=offer.parse(await fetch(root(vehicleId)+"/offer",{
    method:"POST",cache:"no-store",
    body:JSON.stringify({
      target_driver_id:Number(driverId),
      expected_context_revision:ready.context_revision,
      expected_stock_snapshot:ready.stock_snapshot,
    }),
  }));
  if(response.stock_snapshot!==stock.stock_snapshot||
     response.stock_line_count!==stock.stock_lines.length)throw new Error("C03_STOCK_SNAPSHOT_STALE");
  return response;
}
// Only a UUID (not a signed offer, receipt, password or stock) survives a tab refresh.
// The UUID is scoped to the exact authenticated principal and vehicle.
export const pendingKey=(scope:string,car:string)=>"wanasah:c03:accept:"+scope+":"+car;
export const pendingRead=(key:string)=>{try{return sessionStorage.getItem(key);}catch{return null;}};
export const pendingSave=(key:string,uuid:string)=>{try{sessionStorage.setItem(key,uuid);}catch{/* in-memory retry still works */}};
export const pendingClear=(key:string)=>{try{sessionStorage.removeItem(key);}catch{/* no proof stored */}};
export const statusByRequest=async(fetch:AuthorizedFetch,car:string,uuid:string)=>
  lookup.parse(await fetch(root(car)+"/accept-operations/"+encodeURIComponent(uuid),{cache:"no-store"}));

export type Outcome={kind:"committed";receipt:z.infer<typeof accepted>}|
  {kind:"denied"|"conflict"|"unknown";code?:string};
import type { z } from "zod";
export async function acceptOnce(fetch:AuthorizedFetch,car:string,uuid:string,proof:string):Promise<Outcome>{
  try{
    const result=accepted.parse(await fetch(root(car)+"/accept",{
      method:"POST",cache:"no-store",
      body:JSON.stringify({request_id:uuid,receiver_proof:proof}),
    }));
    if(result.vehicle_id!==Number(car))throw new Error("C03_WRONG_VEHICLE");
    return {kind:"committed",receipt:result};
  }catch(error){
    const status=apiErrorStatus(error),code=apiErrorCode(error);
    return {kind:status===401||status===403?"denied":
      status===409||status===422?"conflict":"unknown",code};
  }
}
