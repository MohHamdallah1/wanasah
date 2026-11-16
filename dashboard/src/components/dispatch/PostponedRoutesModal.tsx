import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import type { PendingRoute } from "@/types/dispatch";
import { activeRouteText, type ActiveRouteTextKey } from "@/features/dispatch/routeLifecycle/activeRouteCopy";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  routes: PendingRoute[];
  onRestore: (id: string) => void;
  onCloseRoute: (id: string) => void;
}

/** Postponed is a RESERVED zone, never an occupied vehicle or rep. */
export function PostponedRoutesModal({isOpen,onClose,routes,onRestore,onCloseRoute}:Props) {
  const {i18n}=useTranslation();
  const t=(key:ActiveRouteTextKey)=>activeRouteText(i18n.language,key);
  const postponed=routes.filter(route=>route.status==="postponed");
  return <Modal isOpen={isOpen} onClose={onClose}
    title={t("titlePostponed")} maxWidth="max-w-4xl">
    <div dir={i18n.dir()} className="min-w-0 space-y-3">
      <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        role="note">{t("postponedDetails")}</p>
      {!postponed.length ? <p className="py-8 text-center text-sm text-slate-500">
        {t("noPostponed")}
      </p> : <div className="max-w-full overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-0 text-sm">
          <thead><tr className="bg-slate-50">
            <th scope="col" className="p-3 text-start">{t("zone")}</th>
            <th scope="col" className="p-3 text-start">{t("assignment")}</th>
            <th scope="col" className="p-3 text-center">{t("shops")}</th>
            <th scope="col" className="p-3 text-start">{t("actions")}</th>
          </tr></thead>
          <tbody>{postponed.map(route=><tr key={route.id} className="border-t border-slate-100"
            data-testid={"postponed-route-"+route.id}>
            <td className="p-3 font-semibold break-words">{route.zoneName}</td>
            <td className="p-3 text-slate-700">{t("postponed")}</td>
            <td className="p-3 text-center tabular-nums">
              {new Intl.NumberFormat(i18n.language.startsWith("ar")?"ar":"en").format(route.shopsRemaining)}
            </td>
            <td className="p-3">
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" disabled={route.can_execute!==true}
                  onClick={()=>onRestore(route.id)}
                  aria-label={t(route.assignmentContextRevision===1 && route.currentPeriodId==null
                    ? "restoreLegacy" : "selectResume")+" "+route.zoneName}
                  className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40">
                  <RotateCcw aria-hidden="true" className="h-4 w-4"/>
                  {t(route.assignmentContextRevision===1 && route.currentPeriodId==null
                    ? "restoreLegacy" : "selectResume")}
                </button>
                <button type="button" disabled={route.can_execute!==true}
                  aria-label={t("close")+" "+route.zoneName}
                  onClick={()=>onCloseRoute(route.id)}
                  className="min-h-10 rounded-lg border border-red-200 px-3 py-2 text-sm font-semibold text-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40">
                  {t("close")}
                </button>
              </div>
            </td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>
  </Modal>;
}
