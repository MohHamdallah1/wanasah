import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CarFront, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { RepresentativesTab } from "./representatives/RepresentativesTab";
import { VehiclesTab } from "./vehicles/VehiclesTab";

type PageTab = "representatives" | "vehicles";

const pageTabFromUrl = (value: string | null): PageTab | null =>
  value === "representatives" || value === "vehicles" ? value : null;

export default function RepresentativesVehiclesPage() {
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess();
  const location = useLocation();
  const navigate = useNavigate();
  const canReadRepresentatives = Boolean(
    access.isCompanyOwner || access.can("representative.read"),
  );
  const canReadVehicles = Boolean(
    access.isCompanyOwner || access.can("vehicle.read"),
  );
  const rawTab = new URLSearchParams(location.search).get("tab");
  const requestedTab = pageTabFromUrl(rawTab);
  const firstReadableTab: PageTab | null = canReadRepresentatives
    ? "representatives"
    : canReadVehicles
      ? "vehicles"
      : null;
  const requestedTabAllowed = requestedTab === "representatives"
    ? canReadRepresentatives
    : requestedTab === "vehicles"
      ? canReadVehicles
      : false;
  const activeTab: PageTab = requestedTab && requestedTabAllowed
    ? requestedTab
    : firstReadableTab ?? "representatives";
  const [visitedTabs, setVisitedTabs] = useState<Set<PageTab>>(
    () => new Set<PageTab>(),
  );

  const navigateToTab = (tab: PageTab, replace: boolean) => {
    const params = new URLSearchParams(location.search);
    params.set("tab", tab);
    navigate(
      { pathname: location.pathname, search: `?${params.toString()}`, hash: location.hash },
      { replace },
    );
  };

  const activate = (tab: PageTab) => {
    const allowed = tab === "representatives" ? canReadRepresentatives : canReadVehicles;
    if (!allowed || tab === activeTab) return;
    setVisitedTabs((current) => {
      const next = new Set(current);
      next.add(tab);
      return next;
    });
    navigateToTab(tab, false);
  };

  useEffect(() => {
    if (access.isLoading || firstReadableTab === null) return;
    setVisitedTabs((current) => {
      if (current.has(activeTab)) return current;
      const next = new Set(current);
      next.add(activeTab);
      return next;
    });
    if (rawTab !== activeTab) {
      const params = new URLSearchParams(location.search);
      params.set("tab", activeTab);
      navigate(
        { pathname: location.pathname, search: `?${params.toString()}`, hash: location.hash },
        { replace: true },
      );
    }
  }, [
    access.isLoading,
    activeTab,
    firstReadableTab,
    location.hash,
    location.pathname,
    location.search,
    navigate,
    rawTab,
  ]);

  const noReadableTab = !access.isLoading && !canReadRepresentatives && !canReadVehicles;

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
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "representatives"}
              aria-disabled={!canReadRepresentatives}
              disabled={access.isLoading || !canReadRepresentatives}
              onClick={() => activate("representatives")}
              className={`inline-flex h-8 items-center gap-2 rounded-lg px-3 text-xs font-black shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-40 ${activeTab === "representatives" ? "bg-white text-slate-900" : "text-slate-200 hover:bg-white/10"}`}
            >
              <UsersRound className="h-4 w-4" />{t("representativesVehicles.tabs.representatives")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "vehicles"}
              aria-disabled={!canReadVehicles}
              disabled={access.isLoading || !canReadVehicles}
              onClick={() => activate("vehicles")}
              className={`inline-flex h-8 items-center gap-2 rounded-lg px-3 text-xs font-black shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-40 ${activeTab === "vehicles" ? "bg-white text-slate-900" : "text-slate-200 hover:bg-white/10"}`}
            >
              <CarFront className="h-4 w-4" />{t("representativesVehicles.tabs.vehicles")}
            </button>
          </div>
        </div>
      </WorkspaceTopBar>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col px-3 pb-3 pt-2 sm:px-4">
        <div className="mx-auto flex min-h-0 w-full max-w-[1500px] flex-1 flex-col">
          {access.isLoading ? (
            <div className="grid min-h-[320px] flex-1 place-items-center text-sm font-bold text-slate-500" role="status">
              {t("common.loading")}
            </div>
          ) : noReadableTab ? (
            <div className="grid min-h-[320px] flex-1 place-items-center rounded-[26px] border border-white/85 bg-white/70 p-6 text-center text-sm font-bold text-slate-600 shadow-sm">
              {t("representativesVehicles.noAccess")}
            </div>
          ) : (
            <>
              {canReadRepresentatives && visitedTabs.has("representatives") ? (
                <div className={activeTab === "representatives" ? "flex min-h-0 flex-1 flex-col" : "hidden"} aria-hidden={activeTab !== "representatives"}>
                  <RepresentativesTab />
                </div>
              ) : null}
              {canReadVehicles && visitedTabs.has("vehicles") ? (
                <div className={activeTab === "vehicles" ? "flex min-h-0 flex-1 flex-col" : "hidden"} aria-hidden={activeTab !== "vehicles"}>
                  <VehiclesTab />
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
