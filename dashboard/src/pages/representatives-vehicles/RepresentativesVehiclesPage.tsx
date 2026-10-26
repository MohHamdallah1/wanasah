import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CarFront, Truck, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import SuppliersPage from "../suppliers/SuppliersPage";
import { RepresentativesTab } from "./representatives/RepresentativesTab";
import { VehiclesTab } from "./vehicles/VehiclesTab";

type PageTab = "representatives" | "vehicles" | "suppliers";

const pageTabFromUrl = (value: string | null): PageTab | null =>
  value === "representatives" || value === "vehicles" || value === "suppliers" ? value : null;

const tabPreferenceKey = (companyId?: number, principalId?: number): string | null => {
  if (
    typeof companyId !== "number" || typeof principalId !== "number"
    || !Number.isSafeInteger(companyId) || !Number.isSafeInteger(principalId)
    || companyId <= 0 || principalId <= 0
  ) return null;
  return `wanasah:layout:representatives-vehicles:tab:v1:${companyId}:${principalId}`;
};

const readTabPreference = (key: string | null): PageTab | null => {
  if (!key) return null;
  try {
    return pageTabFromUrl(localStorage.getItem(key));
  } catch {
    return null;
  }
};

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
  const canReadSuppliers = Boolean(
    access.isCompanyOwner || access.can("supplier.read"),
  );
  const rawTab = new URLSearchParams(location.search).get("tab");
  const requestedTab = pageTabFromUrl(rawTab);
  const firstReadableTab: PageTab | null = canReadRepresentatives
    ? "representatives"
    : canReadVehicles
      ? "vehicles"
      : canReadSuppliers
        ? "suppliers"
        : null;
  const preferenceKey = tabPreferenceKey(access.data?.company_id, access.data?.principal_id);
  const storedTab = readTabPreference(preferenceKey);
  const canReadTab = (tab: PageTab | null): boolean => tab === "representatives"
    ? canReadRepresentatives
    : tab === "vehicles"
      ? canReadVehicles
      : tab === "suppliers"
        ? canReadSuppliers
        : false;
  const activeTab: PageTab = requestedTab && canReadTab(requestedTab)
    ? requestedTab
    : storedTab && canReadTab(storedTab)
      ? storedTab
      : firstReadableTab ?? "representatives";
  const [visitedTabs, setVisitedTabs] = useState<Set<PageTab>>(
    () => new Set<PageTab>(),
  );

  const navigateToTab = useCallback((tab: PageTab, replace: boolean) => {
    const params = new URLSearchParams(location.search);
    params.set("tab", tab);
    navigate(
      { pathname: "/representatives-vehicles", search: `?${params.toString()}`, hash: location.hash },
      { replace },
    );
  }, [location.hash, location.search, navigate]);

  const activate = (tab: PageTab) => {
    if (!canReadTab(tab) || tab === activeTab) return;
    setVisitedTabs((current) => {
      const next = new Set(current);
      next.add(tab);
      return next;
    });
    navigateToTab(tab, false);
  };

  useEffect(() => {
    if (access.isLoading || firstReadableTab === null) return;
    if (preferenceKey) {
      try {
        localStorage.setItem(preferenceKey, activeTab);
      } catch {
        // A browser preference must never block authorized tab navigation.
      }
    }
    setVisitedTabs((current) => {
      if (current.has(activeTab)) return current;
      const next = new Set(current);
      next.add(activeTab);
      return next;
    });
    if (location.pathname !== "/representatives-vehicles" || rawTab !== activeTab) {
      navigateToTab(activeTab, true);
    }
  }, [
    access.isLoading,
    activeTab,
    firstReadableTab,
    location.pathname,
    navigateToTab,
    preferenceKey,
    rawTab,
  ]);

  const noReadableTab = !access.isLoading
    && !canReadRepresentatives
    && !canReadVehicles
    && !canReadSuppliers;

  const tabClass = (selected: boolean) => `inline-flex min-h-10 min-w-0 items-center justify-center gap-2 rounded-xl border px-4 text-xs font-black shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 disabled:cursor-not-allowed disabled:opacity-40 ${selected
    ? "border-amber-400 bg-amber-400 text-slate-950 hover:bg-amber-300"
    : "border-white/10 bg-white/[0.06] text-slate-100 hover:border-white/15 hover:bg-white/[0.1] hover:text-white"}`;

  return (
    <main className="relative flex min-h-0 flex-1 flex-col gap-2 overflow-visible text-foreground" dir={i18n.dir()}>
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -right-20 top-12 h-72 w-72 rounded-full bg-cyan-200/25 blur-3xl" />
        <div className="absolute bottom-10 left-12 h-72 w-72 rounded-full bg-amber-100/35 blur-3xl" />
      </div>

      <WorkspaceTopBar variant="page" className="shrink-0">
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <header className="min-w-0">
            <h1 className="text-lg font-black leading-6 text-white sm:text-xl">{t("representativesVehicles.title")}</h1>
            <p className="mt-0.5 hidden text-[11px] font-semibold leading-5 text-slate-300/80 sm:block">{t("representativesVehicles.subtitle")}</p>
          </header>

          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:justify-end" role="tablist" aria-label={t("representativesVehicles.title")}>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "representatives"}
              aria-disabled={!canReadRepresentatives}
              disabled={access.isLoading || !canReadRepresentatives}
              onClick={() => activate("representatives")}
              className={tabClass(activeTab === "representatives")}
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
              className={tabClass(activeTab === "vehicles")}
            >
              <CarFront className="h-4 w-4" />{t("representativesVehicles.tabs.vehicles")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "suppliers"}
              aria-disabled={!canReadSuppliers}
              disabled={access.isLoading || !canReadSuppliers}
              onClick={() => activate("suppliers")}
              className={tabClass(activeTab === "suppliers")}
            >
              <Truck className="h-4 w-4" />{t("representativesVehicles.tabs.suppliers")}
            </button>
          </div>
        </div>
      </WorkspaceTopBar>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 w-full flex-1 flex-col">
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
              {canReadSuppliers && visitedTabs.has("suppliers") ? (
                <div className={activeTab === "suppliers" ? "flex min-h-0 flex-1 flex-col" : "hidden"} aria-hidden={activeTab !== "suppliers"}>
                  <SuppliersPage embedded />
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
