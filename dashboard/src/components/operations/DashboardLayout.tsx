import { Menu, WifiOff } from "lucide-react";
import {
  lazy,
  Suspense,
  useEffect,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import {
  Navigate,
  Outlet,
  useLocation,
} from "react-router-dom";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useDashboardSession } from "@/hooks/useDashboardSession";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { loadDispatchBoard, loadInventoryPage } from "@/routes/routePreloaders";
import { DispatchChromeHost } from "@/features/dispatch/stableUi/DispatchChrome";

import "./dashboard.css";
import { OperationsSidebar } from "./OperationsSidebar";

const OPERATIONS_SIDEBAR_COLLAPSED_KEY =
  "wanasah:layout:operations-sidebar-collapsed";

const MainInventory = lazy(loadInventoryPage);
// Defer the business board until Dispatch is actually visited. Other pages must
// not pay for its route/product/finance dependencies at bootstrap.
const PersistentDispatch = lazy(loadDispatchBoard);

const DashboardLayout = () => {
  const { t, i18n } =
    useTranslation();
  const [
    sidebarOpen,
    setSidebarOpen,
  ] = useState(false);
  const [
    sidebarCollapsed,
    setSidebarCollapsed,
  ] = useState(
    () =>
      localStorage.getItem(
        OPERATIONS_SIDEBAR_COLLAPSED_KEY,
      ) === "1",
  );
  const location =
    useLocation();
  const isInventoryRoute =
    location.pathname === "/inventory";
  const isDispatchRoute = location.pathname === "/dispatch";
  // Like Inventory, keep the expensive Dispatch workspace mounted only after its
  // first visit. Its own active-route gate reauthorizes on every reentry.
  const [dispatchMounted, setDispatchMounted] = useState(isDispatchRoute);
  const [
    inventoryMounted,
    setInventoryMounted,
  ] = useState(isInventoryRoute);
  const session =
    useDashboardSession();
  const access =
    useInventoryAccess();
  const isOnline =
    useNetworkStatus();

  useEffect(() => {
    localStorage.setItem(
      OPERATIONS_SIDEBAR_COLLAPSED_KEY,
      sidebarCollapsed
        ? "1"
        : "0",
    );
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (isInventoryRoute) {
      setInventoryMounted(true);
    }
  }, [isInventoryRoute]);

  useEffect(() => {
    if (isDispatchRoute) setDispatchMounted(true);
  }, [isDispatchRoute]);

  if (!session) {
    return <Navigate to="/login" replace />;
  }

  if (access.isPending && !isDispatchRoute) {
    return (
      <div
        className="dashboard-access-state"
        dir={i18n.dir()}
      >
        <span aria-hidden="true" />
        <p>
          {t("access.loading")}
        </p>
      </div>
    );
  }

  if (access.isError && !isDispatchRoute) {
    return (
      <div
        className="dashboard-access-state dashboard-access-state--error"
        dir={i18n.dir()}
      >
        <strong>
          {t("access.failed")}
        </strong>
        <button
          type="button"
          onClick={() =>
            void access.refetch()
          }
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }

  if (
    !access.isCompanyOwner &&
    location.pathname === "/"
  ) {
    return (
      <Navigate
        to="/inventory"
        replace
      />
    );
  }
  if (
    !access.isPending &&
    !access.isError &&
    !access.isCompanyOwner &&
    location.pathname ===
      "/dispatch" &&
    !access.canAny("dispatch.read")
  ) {
    return (
      <Navigate
        to="/inventory"
        replace
      />
    );
  }
  if (
    !access.isCompanyOwner &&
    location.pathname ===
      "/products" &&
    !access.canAny("catalog.read")
  ) {
    return (
      <Navigate
        to="/inventory"
        replace
      />
    );
  }
  if (
    !access.isCompanyOwner &&
    location.pathname ===
      "/pricing" &&
    !access.canAny("pricing.view")
  ) {
    return (
      <Navigate
        to="/inventory"
        replace
      />
    );
  }
  if (
    !access.isCompanyOwner &&
    location.pathname ===
      "/commercial-rules" &&
    !(
      access.canAny("offers.view") ||
      access.canAny("tax.view")
    )
  ) {
    return (
      <Navigate
        to="/inventory"
        replace
      />
    );
  }
  if (
    !access.isCompanyOwner &&
    location.pathname ===
      "/sales-returns"
  ) {
    return (
      <Navigate
        to="/inventory"
        replace
      />
    );
  }

  return (
    <div
      className="dashboard-shell h-screen overflow-hidden mesh-gradient-bg p-3 md:p-4 flex gap-4"
      dir={i18n.dir()}
    >
      <OperationsSidebar
        open={sidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={() =>
          setSidebarOpen(false)
        }
        onToggleCollapsed={() =>
          setSidebarCollapsed(
            (current) => !current,
          )
        }
      />

      <div className="dashboard-main-stage flex min-w-0 flex-1 flex-col">
        <button
          type="button"
          onClick={() =>
            setSidebarOpen(true)
          }
          className="dashboard-mobile-menu fixed end-4 top-4 z-50 flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white shadow-md lg:hidden"
          aria-label={t(
            "nav.openNavigation"
          )}
        >
          <Menu className="h-5 w-5 text-slate-700" />
        </button>

        {!isOnline ? (
          <div
            role="status"
            className="mb-2 flex shrink-0 items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900"
          >
            <WifiOff className="h-4 w-4 shrink-0" />
            <span>
              {t(
                "network.offlineBanner"
              )}
            </span>
          </div>
        ) : null}

        <main className="dashboard-content mt-2 flex min-h-0 flex-1 flex-col gap-4">
          {/* The public dispatch toolbar is a stable sibling of all Suspense boundaries. */}
          {(dispatchMounted || isDispatchRoute) ? (
            <div className={isDispatchRoute ? "contents" : "hidden"}
              aria-hidden={!isDispatchRoute} data-persistent-dispatch-host="true">
              <DispatchChromeHost active={isDispatchRoute}>
                <Suspense fallback={null}>
                  <PersistentDispatch key={`${session.generation}:${session.identity}:dispatch`} />
                </Suspense>
              </DispatchChromeHost>
            </div>
          ) : null}
          <Suspense fallback={
            <div className="grid min-h-0 flex-1 place-items-center rounded-2xl border border-white/50 bg-white/35 text-sm font-bold text-slate-500" role="status">
              {t("common.loading")}
            </div>
          }>
            {inventoryMounted ? (
              <div className={isInventoryRoute ? "contents" : "hidden"}
                aria-hidden={!isInventoryRoute} data-persistent-inventory-host="true">
                <MainInventory key={`${session.generation}:${session.identity}:inventory`} />
              </div>
            ) : null}
            {!isInventoryRoute && !isDispatchRoute ? (
              <Outlet key={`${session.generation}:${session.identity}`} />
            ) : null}
          </Suspense>
        </main>
      </div>
    </div>
  );
};

export default DashboardLayout;
