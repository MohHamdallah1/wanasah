import { Calendar, ClipboardList, LayoutGrid, Plus, Truck } from "lucide-react";
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import "./dispatchNoMotion.css";
import { useTranslation } from "react-i18next";
import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import type { TabId } from "@/types/dispatch";

const ALL_TABS = [
  { id: "routes", label: "الخطوط النشطة", icon: Truck },
  { id: "launch", label: "إطلاق خط جديد", icon: Plus },
  { id: "zones", label: "هيكلة المناطق", icon: LayoutGrid },
] as const;

interface Props {
  activeTab: TabId;
  admitted: boolean;
  permissionKnown: boolean;
  allowedTabs?: readonly TabId[];
  canShortages?: boolean;
  canZoneManage?: boolean;
  hasShortages?: boolean;
  onTabChange?: (tab: TabId) => void;
  onShortages?: () => void;
  onBulkSchedule?: () => void;
}

/** Public, stable tab/action geometry: all commands fail closed until fresh HTTP reads pass. */
export function DispatchChrome({
  activeTab, admitted, permissionKnown, allowedTabs,
  canShortages = false, canZoneManage = false, hasShortages = false,
  onTabChange, onShortages, onBulkSchedule,
}: Props) {
  const { i18n } = useTranslation();
  // Never unmount public tab positions when a scoped permission response arrives.
  const visibleTabs = ALL_TABS;
  const showShortages = true;
  const showScheduling = true;

  return (
    <WorkspaceTopBar variant="page" className="shrink-0" data-testid="dispatch-shared-topbar">
      <header className="flex w-full min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <div className="dispatch-tab-list flex max-w-full min-w-0 overflow-x-auto rounded-xl bg-white/10 p-1"
            role="tablist" aria-label={i18n.language.startsWith("ar") ? "أقسام إدارة التوزيع" : "Dispatch sections"}>
            {visibleTabs.map(tab => (
              <button key={tab.id} type="button" role="tab"
                aria-selected={admitted && activeTab === tab.id}
                disabled={!admitted || (permissionKnown && !allowedTabs?.includes(tab.id))}
                onClick={() => { if (admitted && allowedTabs?.includes(tab.id)) onTabChange?.(tab.id); }}
                className={`dispatch-tab flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-bold sm:px-3 sm:text-sm ${
                  admitted && activeTab === tab.id
                    ? "bg-white text-[#125d85] shadow-sm"
                    : "text-slate-200 hover:bg-white/10 hover:text-white"
                }`}>
                <tab.icon className="h-4 w-4 shrink-0" /> {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex min-w-0 shrink-0 items-center gap-2">
          {showShortages && (
            <button type="button" disabled={!admitted || !canShortages}
              onClick={() => { if (admitted && canShortages) onShortages?.(); }}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold sm:text-sm ${
                admitted && hasShortages
                  ? "border-amber-300 bg-amber-500 text-slate-950"
                  : "border-white/20 bg-white/10 text-white hover:bg-white/20"
              }`}>
              <ClipboardList className="h-4 w-4 shrink-0" />
              طلبات ونواقص
            </button>
          )}
          {activeTab === "zones" && showScheduling && (
            <button type="button" disabled={!admitted || !canZoneManage}
              onClick={() => { if (admitted && canZoneManage) onBulkSchedule?.(); }}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[#1e87bb] px-3 py-2 text-xs font-bold text-white hover:bg-[#166a94] sm:text-sm">
              <Calendar className="h-4 w-4 shrink-0" />
              الجدولة الشاملة
            </button>
          )}
        </div>
      </header>
    </WorkspaceTopBar>
  );
}

type ChromeView = Pick<Props, "activeTab" | "admitted" | "permissionKnown" | "allowedTabs" |
  "canShortages" | "canZoneManage" | "hasShortages">;
type ChromeActions = Pick<Props, "onTabChange" | "onShortages" | "onBulkSchedule">;
type ChromeBridge = { publish: (view: ChromeView, actions: ChromeActions) => void };
const ChromeContext = createContext<ChromeBridge | null>(null);
const initialView: ChromeView = {
  activeTab: "routes", admitted: false, permissionKnown: false, allowedTabs: [],
  canShortages: false, canZoneManage: false, hasShortages: false,
};
export const useDispatchChromeBridge = () => useContext(ChromeContext);

/** One permanent toolbar owned above Dispatch lazy hydration, not a cold duplicate. */
export function DispatchChromeHost({ active, children }: { active: boolean; children: ReactNode }) {
  const [view, setView] = useState<ChromeView>(initialView);
  const handlers = useRef<ChromeActions>({});
  const publish = useCallback((next: ChromeView, callbacks: ChromeActions) => {
    handlers.current = callbacks;
    setView(current =>
      current.activeTab === next.activeTab && current.admitted === next.admitted &&
      current.permissionKnown === next.permissionKnown &&
      current.canShortages === next.canShortages &&
      current.canZoneManage === next.canZoneManage &&
      current.hasShortages === next.hasShortages &&
      current.allowedTabs?.join("|") === next.allowedTabs?.join("|")
        ? current : next,
    );
  }, []);
  const bridge = useMemo(() => ({ publish }), [publish]);
  // On navigation away revoke actions before paint; keep only the public tab preference.
  useLayoutEffect(() => {
    if (!active) {
      handlers.current = {};
      setView(current => ({ ...initialView, activeTab: current.activeTab }));
    }
  }, [active]);
  return (
    <ChromeContext.Provider value={bridge}>
      <div className="dispatch-board flex h-full min-h-0 w-full flex-1 flex-col">
        <DispatchChrome {...view} admitted={active && view.admitted}
          onTabChange={tab => handlers.current.onTabChange?.(tab)}
          onShortages={() => handlers.current.onShortages?.()}
          onBulkSchedule={() => handlers.current.onBulkSchedule?.()} />
        {children}
      </div>
    </ChromeContext.Provider>
  );
}
