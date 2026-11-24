import { useCallback, useEffect, useRef, useState } from "react";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import { apiErrorStatus } from "@/lib/apiErrors";
import type { Shortage } from "@/types/dispatch";
import { allowedUrgentDriver, clearUrgent, parseUrgentQuote, parseUrgentReceipt, positive, readUrgent, storeUrgent, urgentBudget,
  type EligibleDriver, type UrgentPending } from "./contract";

type Fetch = (path:string, options?:RequestInit) => Promise<unknown>;
type Feedback = "unknown" | "conflict" | "denied" | "storage" | "another-tab" | "stale" | "committed" | "refresh";
type Props = { session:DashboardSession; scope:string|null; authorized:boolean; ready:boolean; fetch:Fetch;
  rows:readonly Shortage[]; drivers:readonly EligibleDriver[]; canSee:(row:Shortage)=>boolean;
  onRestore:()=>void; refresh:()=>Promise<void> };
type State = { key:string; pending:UrgentPending|null; busy:boolean; feedback:Feedback|null; blocked:boolean };
const empty = (key:string):State => ({key,pending:null,busy:false,feedback:null,blocked:false});
export function useUrgentPromotion(props:Props) {
  const key = JSON.stringify([props.session,props.scope]);
  const current = useRef({props,key});
  current.current = {props,key};
  const [state,setState] = useState<State>(()=>empty(key));
  const flight = useRef(false);
  const generation = useRef(0);
  const denied = useRef(false);
  const mounted = useRef(true);
  const scoped = (p:Props, original:UrgentPending) => p.rows.some(row =>
    row.id === String(original.shortageId) && row.shopId === String(original.shopId) &&
    row.zoneId === String(original.zoneId) && row.productId === String(original.productId) &&
    p.canSee(row) && p.drivers.some(driver => driver.id === String(original.body.driver_id) && allowedUrgentDriver(row,driver)));
  const live = useCallback((ownKey:string, ownGeneration:number, requireReady=true) => {
    const now=current.current;
    return mounted.current && now.key===ownKey && generation.current===ownGeneration && !denied.current &&
      now.props.authorized && (!requireReady || now.props.ready) && !!now.props.scope && isDashboardSessionCurrent(now.props.session);
  },[]);
  useEffect(()=>{
    mounted.current=true;
    const revoke=()=>{generation.current++;denied.current=true;setState({...empty(current.current.key),blocked:true,feedback:"denied"});};
    window.addEventListener("inventory-permission-denied",revoke);
    return ()=>{mounted.current=false;generation.current++;window.removeEventListener("inventory-permission-denied",revoke);};
  },[]);
  useEffect(()=>{
    generation.current++;
    denied.current=false;
    setState(empty(key));
    if(!props.authorized || !props.ready || !props.scope || !isDashboardSessionCurrent(props.session))return;
    try{
      const saved=readUrgent(props.scope);
      if(saved){
        if(!scoped(props,saved)){setState({...empty(key),blocked:true,feedback:"denied"});return;}
        setState({...empty(key),pending:saved,feedback:"unknown"});props.onRestore();
      }
    }catch{setState({...empty(key),blocked:true,feedback:"storage"});}
    // Re-read only on identity/admission changes, not ordinary list updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[key,props.authorized,props.ready]);
  const active = state.key===key ? state : empty(key);
  const visible = props.authorized && props.ready && !denied.current && isDashboardSessionCurrent(props.session);
  const pendingVisible = visible && active.pending && scoped(props,active.pending) ? active.pending : null;
  const hiddenPending = !!active.pending && !pendingVisible;
  const perform = async (newRequest?:{shortageId:string;driverId:string;quantity:number}) => {
    const ownKey=key, ownGeneration=generation.current, scope=props.scope;
    if(!scope || !live(ownKey,ownGeneration) || flight.current || active.blocked || hiddenPending) return false;
    if(!navigator.locks?.request){setState({...empty(key),blocked:true,feedback:"storage"});return false;}
    flight.current=true;
    setState(s=>({...s,key,busy:true,feedback:null}));
    const publish=(patch:Partial<State>)=>{if(live(ownKey,ownGeneration,false))setState(s=>({...s,...patch,key:ownKey}));};
    try{
      return await navigator.locks.request("wanasah:shortage-urgent:v1:"+scope,{mode:"exclusive",ifAvailable:true},async lock=>{
        if(!live(ownKey,ownGeneration))return false;
        if(!lock){publish({feedback:"another-tab"});return false;}
        let original:UrgentPending|null=null;
        try{
          original=readUrgent(scope);
          if(original){
            if(!scoped(current.current.props,original)){publish({pending:null,blocked:true,feedback:"denied"});return false;}
            if(newRequest){publish({pending:original,feedback:"unknown"});return false;}
          }else{
            if(!newRequest){publish({pending:null,feedback:"stale"});return false;}
            const p=current.current.props;
            const row=p.rows.find(r=>r.id===newRequest.shortageId);
            const driver=p.drivers.find(d=>d.id===newRequest.driverId);
            const budget=row&&urgentBudget(row);
            if(!row || !driver || !budget || !p.canSee(row) || !allowedUrgentDriver(row,driver) ||
               !positive(newRequest.quantity) || newRequest.quantity>budget.unassigned){publish({feedback:"stale"});return false;}
            // Fresh exact quote immediately before durable new command, never on replay.
            const params=new URLSearchParams({driver_id:driver.id,product_ids:row.productId});
            let raw:unknown;
            try{raw=await p.fetch("/dispatch/shortages/vehicle-availability?"+params,{cache:"no-store"});}
            catch(error){publish({feedback:apiErrorStatus(error)===403?"denied":"stale"});return false;}
            if(!live(ownKey,ownGeneration))return false;
            const latest=current.current.props;
            const latestRow=latest.rows.find(r=>r.id===row.id);
            const latestDriver=latest.drivers.find(d=>d.id===driver.id);
            const quote=latestRow&&latestDriver&&latest.canSee(latestRow)&&parseUrgentQuote(raw,latestRow,latestDriver);
            if(!quote || newRequest.quantity>quote.limit || !latestRow || !latestDriver){publish({feedback:"stale"});return false;}
            original=storeUrgent(scope,latestRow,latestDriver,newRequest.quantity);
          }
        }catch{publish({blocked:true,feedback:"storage"});return false;}
        if(!original || !live(ownKey,ownGeneration) || !scoped(current.current.props,original))return false;
        publish({pending:original});
        try{
          const raw=await current.current.props.fetch("/dispatch/shortages/"+original.shortageId+"/promote-urgent",
            {method:"POST",body:JSON.stringify(original.body)});
          if(!live(ownKey,ownGeneration,false) || !scoped(current.current.props,original))return false;
          const receipt=parseUrgentReceipt(raw,original);
          if(!receipt){publish({feedback:"unknown"});return false;}
          // Only the exact immutable POST receipt resolves the durable envelope.
          clearUrgent(scope,original);
          publish({pending:null,feedback:"committed"});
          try{await current.current.props.refresh();}
          catch{publish({blocked:true,feedback:"refresh"});}
          return true;
        }catch(error){
          const status=apiErrorStatus(error);
          if(status===401||status===403){publish({pending:null,blocked:true,feedback:"denied"});}
          else publish({pending:original,feedback:status===409?"conflict":"unknown"});
          return false;
        }
      });
    }catch{publish({blocked:true,feedback:"storage"});return false;}
    finally{flight.current=false;publish({busy:false});}
  };
  return {
    authorized:visible, drivers:props.drivers, fetch:props.fetch, canSee:props.canSee, pending:pendingVisible,
    busy:visible&&active.busy, blocked:active.blocked||hiddenPending,
    feedback:visible?(hiddenPending?"denied" as const:active.feedback):null,
    unresolved:!!active.pending||active.blocked||active.busy,
    submit:(shortageId:string,driverId:string,quantity:number)=>perform({shortageId,driverId,quantity}),
    retry:()=>perform(),
  };
}
export type UrgentPromotion = ReturnType<typeof useUrgentPromotion>;
