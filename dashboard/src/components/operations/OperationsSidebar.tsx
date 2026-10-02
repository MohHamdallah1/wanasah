import { useEffect, useRef, useState } from "react";
import {
  BadgePercent,
  Calendar,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  FileText,
  LogOut,
  MapPin,
  Package,
  PackagePlus,
  Radar,
  RotateCcw,
  Settings,
  Truck,
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
import { clearLocalStoragePreservingLoginHintsAndPreferences } from "@/lib/authStorage";
import { resolveI18nLocale } from "@/lib/locale";
import { preloadProductsPage } from "@/routes/routePreloaders";

interface OperationsSidebarProps {
  open: boolean;
  collapsed: boolean;
  onClose: () => void;
  onToggleCollapsed: () => void;
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
  collapsed,
  onClose,
  onToggleCollapsed,
}: OperationsSidebarProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const access = useInventoryAccess();
  const tenantIdentity =
    useTenantIdentity();
  const location = useLocation();
  const isRtl =
    i18n.dir() === "rtl";

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

    clearLocalStoragePreservingLoginHintsAndPreferences();
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
        data-collapsed={
          collapsed
            ? "true"
            : "false"
        }
        className={`
          operations-sidebar fixed inset-y-0 end-0 z-50 flex w-[250px] flex-col glass-sidebar p-5 transition-[transform,width,padding] duration-300
          lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] lg:translate-x-0 lg:rounded-2xl lg:border lg:z-auto
          ${collapsed
            ? "lg:w-[76px] lg:p-2.5"
            : "lg:w-[250px] lg:p-5"}
          ${
            open
              ? "translate-x-0"
              : "translate-x-full lg:translate-x-0"
          }
        `}
      >
        <div
          className={`sidebar-profile relative ${
            collapsed
              ? "mb-4"
              : "mb-6"
          }`}
          ref={dropdownRef}
        >
          <div
            className={`flex items-stretch gap-2 ${
              collapsed
                ? "lg:justify-center"
                : ""
            }`}
          >
            <button
              type="button"
              onClick={() =>
                setIsDropdownOpen(
                  (current) =>
                    !current
                )
              }
              className={`sidebar-account-button min-w-0 flex-1 items-center justify-between rounded-xl border px-3 py-2 shadow-sm transition-all ${
                collapsed
                  ? "flex lg:hidden"
                  : "flex"
              }`}
            >
              <div className="min-w-0 flex flex-col items-start">
                <span className="max-w-full truncate text-sm font-extrabold tracking-tight text-foreground">
                  {adminName}
                </span>
                <span className="max-w-full truncate text-[10px] font-bold text-muted-foreground">
                  {access.isCompanyAdmin
                    ? t(
                        "nav.systemAdmin"
                      )
                    : t(
                        "nav.inventoryUser"
                      )}
                </span>
              </div>

              <ChevronDown
                className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-300 ${
                  isDropdownOpen
                    ? "rotate-180"
                    : ""
                }`}
              />
            </button>

            <button
              type="button"
              onClick={() => {
                setIsDropdownOpen(false);
                onToggleCollapsed();
              }}
              aria-label={t(
                collapsed
                  ? "nav.expandNavigation"
                  : "nav.collapseNavigation",
              )}
              title={t(
                collapsed
                  ? "nav.expandNavigation"
                  : "nav.collapseNavigation",
              )}
              className="hidden h-10 w-10 shrink-0 items-center justify-center self-center rounded-xl border border-white/10 bg-white/5 text-slate-300 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 lg:inline-flex"
            >
              {collapsed ? (
                isRtl ? (
                  <ChevronsLeft className="h-4 w-4" />
                ) : (
                  <ChevronsRight className="h-4 w-4" />
                )
              ) : isRtl ? (
                <ChevronsRight className="h-4 w-4" />
              ) : (
                <ChevronsLeft className="h-4 w-4" />
              )}
            </button>
          </div>

          {isDropdownOpen ? (
            <div
              className={`absolute end-0 top-full z-[80] mt-2 w-full overflow-hidden rounded-xl border border-border bg-white shadow-lg animate-in fade-in slide-in-from-top-2 ${
                collapsed
                  ? "lg:w-64"
                  : ""
              }`}
            >
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
                  onPointerEnter={
                    item.path ===
                    "/products"
                      ? preloadProductsPage
                      : undefined
                  }
                  onFocus={
                    item.path ===
                    "/products"
                      ? preloadProductsPage
                      : undefined
                  }
                  onClick={() =>
                    handleNav(item)
                  }
                  data-active={
                    active
                  }
                  aria-label={
                    collapsed
                      ? t(item.labelKey)
                      : undefined
                  }
                  title={
                    collapsed
                      ? t(item.labelKey)
                      : undefined
                  }
                  className={`operations-nav-item flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-all duration-200 ${
                    collapsed
                      ? "lg:justify-center lg:gap-0 lg:px-0"
                      : ""
                  } ${
                    active
                      ? "bg-primary/15 text-primary-foreground font-bold shadow-sm"
                      : "text-muted-foreground hover:bg-white/60 hover:text-foreground"
                  }`}
                >
                  <item.icon
                    className="h-[18px] w-[18px]"
                    strokeWidth={1.5}
                  />
                  <span
                    className={
                      collapsed
                        ? "lg:sr-only"
                        : ""
                    }
                  >
                    {t(item.labelKey)}
                  </span>
                </button>
              );
            })}
        </nav>

        <div
          className={`sidebar-context mt-auto ${
            collapsed
              ? "pt-3"
              : "pt-6"
          }`}
        >
          <div
            className={`flex flex-col gap-3 rounded-2xl border border-white/50 bg-white/40 p-4 shadow-sm backdrop-blur-md ${
              collapsed
                ? "lg:hidden"
                : ""
            }`}
          >
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

          {collapsed ? (
            <div className="hidden flex-col items-center gap-2 lg:flex">
              <div
                title={currentDate}
                aria-label={currentDate}
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-300"
              >
                <Calendar
                  className="h-4 w-4"
                  strokeWidth={2}
                />
              </div>
              <div
                title={displayLocation}
                aria-label={displayLocation}
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-amber-300"
              >
                <MapPin
                  className="h-4 w-4"
                  strokeWidth={2}
                />
              </div>
            </div>
          ) : null}
        </div>
      </aside>
    </>
  );
}
