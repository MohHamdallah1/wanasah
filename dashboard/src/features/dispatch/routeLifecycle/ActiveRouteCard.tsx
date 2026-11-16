import { AlertTriangle, CircleStop, Clock, Lock, Package, Radar, Truck, UserMinus } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { PendingRoute } from "@/types/dispatch";
import { activeRouteText, type ActiveRouteTextKey } from "./activeRouteCopy";

export interface ActiveRouteActions {
  onOpenRouteModal: (route: PendingRoute, type: "follow_up" | "transfer") => void;
  onPostponeRoute: (id: string) => void;
  onCloseZone: (route: PendingRoute) => void;
  onForceWithdraw: (route: PendingRoute) => void;
  onContinuePaused?: (route: PendingRoute) => void;
  onAdjustInventory: (route: PendingRoute) => void;
  onOpenRadar: (route: PendingRoute) => void;
  driverShortagesMap: Record<string, number>;
}

interface Props extends ActiveRouteActions {
  route: PendingRoute;
  pending: boolean;
}

/** A read-only operational card. No route status or stock mutations are made here. */
export function ActiveRouteCard({route, pending, driverShortagesMap,
  onOpenRouteModal, onPostponeRoute, onCloseZone, onForceWithdraw,
  onContinuePaused, onAdjustInventory, onOpenRadar}: Props) {
  const {i18n}=useTranslation();
  const lang=i18n.language;
  const t=(key:ActiveRouteTextKey,vars?:Record<string,string|number>)=>activeRouteText(lang,key,vars);
  const safe=()=>pending ? t("checkingAccess") :
    route.can_execute===true ? undefined : t("actionUnavailable");
  const isWaiting=route.status==="waiting";
  const isVersioned=route.assignmentContextRevision !== 1 || route.currentPeriodId != null;
  const signedWaiting= !isVersioned || (route.currentPeriodId != null &&
    route.currentDriverId != null && route.currentVehicleId != null);
  const mayExecute=route.can_execute===true;
  const canExecute=mayExecute && !pending;
  const driverName=route.currentDriverName ||
    (route.assignmentContextRevision === 1 ? route.driverName : null) || t("noDriver");
  const currentDriver=route.currentDriverId ??
    (route.assignmentContextRevision===1 ? Number(route.driverId) : null);
  const urgent=currentDriver ? driverShortagesMap[String(currentDriver)]||0 : 0;
  const locale=i18n.language.startsWith("ar")?"ar":"en";
  const lockTime=(value:string)=>{
    const date=new Date(value);
    return Number.isNaN(date.getTime())?t("invalidTime"):
      new Intl.DateTimeFormat(locale,{dateStyle:"short",timeStyle:"short"}).format(date);
  };
  const actionClass="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-bold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1e87bb] disabled:cursor-not-allowed disabled:opacity-40";
  const radar=<button type="button" disabled={pending} title={t("radar")} aria-label={t("radar")}
    onClick={()=>onOpenRadar(route)} className={actionClass+" border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"}>
    <Radar aria-hidden="true" className="h-4 w-4"/>
  </button>;
  const close=<button type="button" disabled={!canExecute} title={safe()}
    onClick={()=>onCloseZone(route)} className={actionClass+" border-red-200 bg-red-50 text-red-700 hover:bg-red-100"}>
    <AlertTriangle aria-hidden="true" className="h-4 w-4"/>{t("close")}
  </button>;
  const postpone=<button type="button" disabled={!canExecute} title={safe()}
    onClick={()=>onPostponeRoute(route.id)} className={actionClass+" border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"}>
    <Clock aria-hidden="true" className="h-4 w-4"/>{t("postpone")}
  </button>;
  const actions=()=>{
    // No mutable commands for a read-only route, even if its status is active.
    if(!mayExecute) return radar;
    // The ended WorkSession cannot resume, irrespective of shops remaining.
    if(route.sessionEnded) return <>{radar}
      <span title={t("workSessionEndedDetail")} className="inline-flex items-center gap-2 rounded-xl border bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">
        <Lock aria-hidden="true" className="h-4 w-4"/>{t("workSessionEnded")}
      </span>{postpone}{close}</>;
    if(isWaiting) return <>{radar}
      <button type="button" disabled={!canExecute || !signedWaiting || (isVersioned && !onContinuePaused)}
        title={!signedWaiting?t("waitingUnverified"):undefined}
        onClick={()=>isVersioned ? onContinuePaused?.(route) : onOpenRouteModal(route,"follow_up")}
        className={actionClass+" border-blue-600 bg-[#1e87bb] text-white hover:bg-blue-700"}>
        {isVersioned?t("continue"):route.sessionBound?t("followUp"):t("followUpLoad")}
      </button>
      {!route.sessionBound && !isVersioned && <button type="button" disabled={!canExecute}
        onClick={()=>onOpenRouteModal(route,"transfer")}
        className={actionClass+" border-slate-200 text-slate-700 hover:bg-slate-50"}>
        <UserMinus aria-hidden="true" className="h-4 w-4"/>{t("reassign")}
      </button>}
      {postpone}{close}
    </>;
    if(route.shopsRemaining===0) return <>{radar}
      <button type="button" disabled={!canExecute} onClick={()=>onCloseZone(route)}
        className={actionClass+" border-emerald-300 bg-emerald-600 text-white hover:bg-emerald-700"}>
        {t("closeFinished")}
      </button>
    </>;
    return <>{radar}
      <button type="button" disabled={!canExecute} onClick={()=>onAdjustInventory(route)}
        className={actionClass+" border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"}>
        <Package aria-hidden="true" className="h-4 w-4"/>{t("adjustLoad")}
      </button>
      <button type="button" disabled={!canExecute} onClick={()=>onForceWithdraw(route)}
        className={actionClass+" border-red-200 bg-red-50 text-red-700 hover:bg-red-100"}>
        <CircleStop aria-hidden="true" className="h-4 w-4"/>{t("pause")}
      </button>
    </>;
  };

  return <article data-testid={"active-route-"+route.id}
    className="dispatch-route-row flex min-w-0 flex-col gap-3 p-4 transition-colors hover:bg-slate-50 xl:flex-row xl:items-center xl:justify-between">
    <div className="flex min-w-0 items-start gap-3">
      <span aria-hidden="true" className={isWaiting
        ? "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-700"
        : "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700"}>
        <Truck className="h-5 w-5"/>
      </span>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="max-w-full break-words text-base font-bold text-slate-800">{route.zoneName}</h3>
        <span className={isWaiting
          ? "rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-bold text-amber-900"
          : "rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-bold text-emerald-900"}>
          {isWaiting ? t(signedWaiting?"waiting":"waitingUnverified") : t("active")}
        </span>
        <span className="text-sm text-slate-600">{t("driver",{name:driverName})}</span>
        <span className="text-sm font-semibold text-slate-700">
          {t("remaining",{count:new Intl.NumberFormat(locale).format(route.shopsRemaining)})}
        </span>
        {urgent>0 && <span className="rounded-full bg-amber-600 px-2 py-0.5 text-xs font-semibold text-white">
          {t("urgent",{count:new Intl.NumberFormat(locale).format(urgent)})}
        </span>}
        {route.commercial_context ? <span
          title={t("commercialTitle",{
            transaction:route.commercial_context.transaction_currency_code,
            functional:route.commercial_context.functional_currency_code,
          })}
          className="inline-flex max-w-full items-center gap-1 rounded-full border bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-700">
          <Lock aria-hidden="true" className="h-3.5 w-3.5 shrink-0"/>
          <span className="break-words">{t("commercialLock",{
            date:lockTime(route.commercial_context.pricing_locked_at),
            price:route.commercial_context.price_publication_revision,
            assignment:route.commercial_context.assignment_revision,
          })}</span>
        </span> : route.sessionBound && <span title={t("commercialUnavailable")}
          className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
          <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5"/>
          {t("commercialUnavailable")}
        </span>}
      </div>
    </div>
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      {actions()}
    </div>
  </article>;
}
