import { Menu, WifiOff } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Navigate,
  Outlet,
  useLocation,
} from "react-router-dom";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";

import "./dashboard.css";
import { OperationsSidebar } from "./OperationsSidebar";

const DashboardLayout = () => {
  const { t, i18n } =
    useTranslation();
  const [
    sidebarOpen,
    setSidebarOpen,
  ] = useState(false);
  const location =
    useLocation();
  const access =
    useInventoryAccess();
  const isOnline =
    useNetworkStatus();

  if (access.isPending) {
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

  if (access.isError) {
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
    !access.isCompanyAdmin &&
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
    !access.isCompanyAdmin &&
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
    !access.isCompanyAdmin &&
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
    !access.isCompanyAdmin &&
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
    !access.isCompanyAdmin &&
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
    !access.isCompanyAdmin &&
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
        onClose={() =>
          setSidebarOpen(false)
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
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default DashboardLayout;
