import { useEffect, useRef, useState } from "react";
import {
  BadgePercent,
  Calendar,
  ChevronDown,
  FileText,
  LogOut,
  MapPin,
  Package,
  PackagePlus,
  Radar,
  RotateCcw,
  Settings,
  Truck,
  User,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
  formatTenantDate,
} from "@/features/tenantIdentity/contracts";
import {
  useTenantIdentity,
} from "@/features/tenantIdentity/useTenantIdentity";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { clearLocalStoragePreservingLastCompanyCode } from "@/lib/authStorage";
import { resolveI18nLocale } from "@/lib/locale";

interface OperationsSidebarProps {
  open: boolean;
  onClose: () => void;
}

const navItems = [
  {
    labelKey: "nav.home",
    icon: Radar,
    path: "/",
  },
  {
    labelKey: "nav.dispatch",
    icon: Truck,
    path: "/dispatch",
  },
  {
    labelKey: "nav.inventory",
    icon: Package,
    path: "/inventory",
  },
  {
    labelKey: "nav.products",
    icon: PackagePlus,
    path: "/products",
  },
  {
    labelKey: "nav.commercialRules",
    icon: BadgePercent,
    path: "/commercial-rules",
  },
  {
    labelKey: "nav.salesReturns",
    icon: RotateCcw,
    path: "/sales-returns",
  },
  {
    labelKey: "nav.reports",
    icon: FileText,
    path: "/reports",
  },
  {
    labelKey: "nav.settings",
    icon: Settings,
    path: "/settings",
  },
] as const;

export function OperationsSidebar({
  open,
  onClose,
}: OperationsSidebarProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const access = useInventoryAccess();
  const tenantIdentity =
    useTenantIdentity();
  const location = useLocation();

  const displayLocation =
    tenantIdentity.data?.display_location ||
    t("nav.locationUnknown");
  const locale =
    resolveI18nLocale(i18n);
  const currentDate = formatTenantDate(
    tenantIdentity.data?.timezone,
    locale
  );

  const adminName =
    localStorage.getItem(
      "admin_name"
    ) || t("nav.administrator");
  const [
    isDropdownOpen,
    setIsDropdownOpen,
  ] = useState(false);
  const dropdownRef =
    useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (
      event: MouseEvent
    ) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(
          event.target as Node
        )
      ) {
        setIsDropdownOpen(false);
      }
    };

    document.addEventListener(
      "mousedown",
      handleClickOutside
    );
    return () =>
      document.removeEventListener(
        "mousedown",
        handleClickOutside
      );
  }, []);

  const handleNav = (
    item: (typeof navItems)[number]
  ) => {
    if (
      item.path === "/" ||
      item.path === "/dispatch" ||
      item.path === "/inventory" ||
      item.path === "/products" ||
      item.path === "/commercial-rules" ||
      item.path === "/sales-returns"
    ) {
      navigate(item.path);
      onClose();
      return;
    }

    toast(
      t("common.comingSoon"),
      {
        description: t(
          "nav.pageInDevelopment",
          {
            page: t(
              item.labelKey
            ),
          }
        ),
        duration: 2000,
      }
    );
  };

  const handleLogout = async () => {
    const API_URL = (
      import.meta.env.VITE_API_URL ||
      ""
    ).replace(/\/$/, "");
    const adminToken =
      localStorage.getItem(
        "admin_token"
      );
    const refreshToken =
      localStorage.getItem(
        "refresh_token"
      );

    if (
      API_URL &&
      adminToken &&
      navigator.onLine
    ) {
      try {
        await Promise.race([
          fetch(
            `${API_URL}/logout`,
            {
              method: "POST",
              headers: {
                "Content-Type":
                  "application/json",
                Authorization:
                  `Bearer ${adminToken}`,
                ...(refreshToken
                  ? {
                      "X-Refresh-Token":
                        refreshToken,
                    }
                  : {}),
              },
            }
          ),
          new Promise(
            (_, reject) =>
              setTimeout(
                () =>
                  reject(
                    new Error(
                      "logout timeout"
                    )
                  ),
                1500
              )
          ),
        ]);
      } catch {
        // Logout is best-effort.
      }
    }

    clearLocalStoragePreservingLastCompanyCode();
    sessionStorage.clear();
    window.location.replace(
      "/login"
    );
  };

  return (
    <>
      {open ? (
        <div
          className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      ) : null}

      <aside
        className={`
          operations-sidebar fixed inset-y-0 end-0 z-50 w-[280px] glass-sidebar p-5 flex flex-col transition-transform duration-300
          lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] lg:translate-x-0 lg:rounded-2xl lg:border lg:z-auto
          ${
            open
              ? "translate-x-0"
              : "translate-x-full lg:translate-x-0"
          }
        `}
      >
        <div
          className="sidebar-profile relative mb-6"
          ref={dropdownRef}
        >
          <button
            type="button"
            onClick={() =>
              setIsDropdownOpen(
                (current) =>
                  !current
              )
            }
            className="flex w-full items-center justify-between rounded-2xl border border-white/50 bg-white/40 p-2.5 shadow-sm transition-all hover:bg-white/60"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-warning shadow-command">
                <User
                  className="h-5 w-5 text-primary-foreground"
                  strokeWidth={1.5}
                />
              </div>
              <div className="flex flex-col items-start">
                <span className="text-sm font-extrabold tracking-tight text-foreground">
                  {adminName}
                </span>
                <span className="text-[10px] font-bold text-muted-foreground">
                  {access.isCompanyAdmin
                    ? t(
                        "nav.systemAdmin"
                      )
                    : t(
                        "nav.inventoryUser"
                      )}
                </span>
              </div>
            </div>

            <ChevronDown
              className={`h-4 w-4 text-muted-foreground transition-transform duration-300 ${
                isDropdownOpen
                  ? "rotate-180"
                  : ""
              }`}
            />
          </button>

          {isDropdownOpen ? (
            <div className="absolute end-0 top-full z-50 mt-2 w-full overflow-hidden rounded-xl border border-border bg-white shadow-lg animate-in fade-in slide-in-from-top-2">
              <div className="p-2">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <Settings className="h-4 w-4" />
                  {t(
                    "nav.accountSettings"
                  )}
                </button>
                <div className="my-1 h-px bg-border" />
                <button
                  type="button"
                  onClick={
                    handleLogout
                  }
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-bold text-destructive transition-colors hover:bg-destructive/10"
                >
                  <LogOut
                    className="h-4 w-4"
                    strokeWidth={2}
                  />
                  {t("nav.logout")}
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <nav
          className="operations-nav flex flex-col gap-1"
          aria-label={t(
            "nav.mainNavigation"
          )}
        >
          {navItems
            .filter(
              (item) =>
                access.isCompanyAdmin ||
                item.path ===
                  "/inventory" ||
                (item.path ===
                  "/dispatch" &&
                  access.canAny(
                    "dispatch.read"
                  )) ||
                (item.path ===
                  "/products" &&
                  access.canAny(
                    "catalog.read"
                  )) ||
                (item.path ===
                  "/commercial-rules" &&
                  (access.canAny(
                    "offers.view"
                  ) ||
                    access.canAny(
                      "tax.view"
                    )))
            )
            .map((item) => {
              const active =
                location.pathname ===
                item.path;
              return (
                <button
                  key={item.path}
                  type="button"
                  onClick={() =>
                    handleNav(item)
                  }
                  data-active={
                    active
                  }
                  className={`operations-nav-item flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-all duration-200 ${
                    active
                      ? "bg-primary/15 text-primary-foreground font-bold shadow-sm"
                      : "text-muted-foreground hover:bg-white/60 hover:text-foreground"
                  }`}
                >
                  <item.icon
                    className="h-[18px] w-[18px]"
                    strokeWidth={1.5}
                  />
                  {t(item.labelKey)}
                </button>
              );
            })}
        </nav>

        <div className="sidebar-context mt-auto pt-6">
          <div className="flex flex-col gap-3 rounded-2xl border border-white/50 bg-white/40 p-4 shadow-sm backdrop-blur-md">
            <div className="flex items-center gap-2.5 text-sm font-bold text-slate-700">
              <div className="rounded-lg bg-primary/10 p-1.5">
                <Calendar
                  className="h-4 w-4 text-primary"
                  strokeWidth={2}
                />
              </div>
              <span className="tracking-tight">
                {currentDate}
              </span>
            </div>

            <div className="flex items-center gap-2.5 text-xs font-bold text-slate-500">
              <div className="rounded-lg bg-warning/10 p-1.5">
                <MapPin
                  className="h-4 w-4 text-warning"
                  strokeWidth={2}
                />
              </div>
              {displayLocation}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
