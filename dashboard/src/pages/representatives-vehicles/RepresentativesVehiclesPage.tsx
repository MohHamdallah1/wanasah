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
        <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-2 sm:flex-nowrap">
          <header className="min-w-0">
            <h1 className="text-lg font-black leading-6 text-white sm:text-xl">{t("representativesVehicles.title")}</h1>
            <p className="mt-0.5 hidden text-[11px] font-semibold leading-5 text-slate-300/80 sm:block">{t("representativesVehicles.subtitle")}</p>
          </header>

          <div className="inline-flex shrink-0 items-center rounded-xl border border-white/15 bg-white/10 p-1 shadow-sm backdrop-blur" role="tablist" aria-label={t("representativesVehicles.title")}>
            <button type="button" role="tab" aria-selected="true"
              className="inline-flex h-8 items-center gap-2 rounded-lg bg-white px-3 text-xs font-black text-slate-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
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
              className="inline-flex h-8 items-center gap-2 rounded-lg px-3 text-xs font-black text-slate-300 opacity-75"
            >
              <CarFront className="h-4 w-4" />{t("representativesVehicles.tabs.vehicles")}
              <span className="hidden rounded-full bg-white/10 px-1.5 py-0.5 text-[9px] font-black text-slate-300 sm:inline">{t("representativesVehicles.vehicles.gated")}</span>
            </button>
            <span id="vehicles-gated-description" className="sr-only">{t("representativesVehicles.vehicles.hint")}</span>
          </div>
        </div>
      </WorkspaceTopBar>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col px-3 pb-3 pt-2 sm:px-4">
        <div className="mx-auto flex min-h-0 w-full max-w-[1500px] flex-1 flex-col">
          <RepresentativesTab />
        </div>
      </div>
    </main>
  );
}
