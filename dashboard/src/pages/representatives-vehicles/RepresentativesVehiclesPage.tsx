import { CarFront, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import { RepresentativesTab } from "./representatives/RepresentativesTab";

export default function RepresentativesVehiclesPage() {
  const { t, i18n } = useTranslation();

  return (
    <main className="relative flex min-h-0 flex-1 flex-col overflow-visible text-foreground" dir={i18n.dir()}>
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -right-20 top-12 h-72 w-72 rounded-full bg-cyan-200/25 blur-3xl" />
        <div className="absolute bottom-10 left-12 h-72 w-72 rounded-full bg-amber-100/35 blur-3xl" />
      </div>

      <WorkspaceTopBar variant="page" className="shrink-0">
        <header className="min-w-0">
          <h1 className="text-lg font-black leading-6 text-white sm:text-xl">{t("representativesVehicles.title")}</h1>
          <p className="mt-0.5 hidden text-[11px] font-semibold leading-5 text-slate-300/80 sm:block">{t("representativesVehicles.subtitle")}</p>
        </header>
      </WorkspaceTopBar>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col px-3 pb-3 pt-3 sm:px-4">
        <div className="mx-auto flex min-h-0 w-full max-w-[1500px] flex-1 flex-col gap-3">
          <div className="inline-flex w-fit items-center rounded-2xl border border-white/80 bg-white/65 p-1 shadow-sm backdrop-blur-xl" role="tablist" aria-label={t("representativesVehicles.title")}>
            <button type="button" role="tab" aria-selected="true"
              className="inline-flex h-9 items-center gap-2 rounded-xl bg-slate-900 px-4 text-xs font-black text-white shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
              <UsersRound className="h-4 w-4" />{t("representativesVehicles.tabs.representatives")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected="false"
              aria-disabled="true"
              aria-describedby="vehicles-gated-description"
              disabled
              title={t("representativesVehicles.vehicles.hint")}
              className="inline-flex h-9 items-center gap-2 rounded-xl px-4 text-xs font-black text-slate-400 opacity-70"
            >
              <CarFront className="h-4 w-4" />{t("representativesVehicles.tabs.vehicles")}
              <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] font-black text-slate-500">{t("representativesVehicles.vehicles.gated")}</span>
            </button>
            <span id="vehicles-gated-description" className="sr-only">{t("representativesVehicles.vehicles.hint")}</span>
          </div>

          <RepresentativesTab />
        </div>
      </div>
    </main>
  );
}
