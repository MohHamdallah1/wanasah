import { AlertTriangle, CheckCircle2, ChevronDown, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import { useLayoutEffect, useRef, useState } from "react";
import {
  PREFLIGHT_AREAS, preflightCopy, preflightLabel, preflightReason,
  type CommercialPreflight, type PreflightArea,
} from "./contract";

type DispatchDestination = "routes" | "zones";

export function CommercialPreflightPanel({
  language, status, evidence, onRefresh, onNavigateToTab, canNavigateToTab,
}: {
  language: string;
  status: "choose" | "loading" | "denied" | "error" | "ready" | "blocked";
  evidence: CommercialPreflight | null;
  onRefresh: () => void;
  onNavigateToTab?: (tab: DispatchDestination) => void;
  canNavigateToTab?: (tab: DispatchDestination) => boolean;
}) {
  const frameRef = useRef<HTMLElement | null>(null);
  const lastVisibleHeightRef = useRef(0);
  const [expanded, setExpanded] = useState(false);
  const pending = status === "loading" || status === "choose";
  const isArabic = language.toLowerCase().startsWith("ar");
  const text = (key: Parameters<typeof preflightCopy>[1]) => preflightCopy(language, key);

  // Preserve the actual slot height through signed reauthorization without
  // retaining confidential evidence or drawing a temporary fake alert.
  useLayoutEffect(() => {
    if (!pending && frameRef.current) {
      lastVisibleHeightRef.current = Math.max(24, frameRef.current.getBoundingClientRect().height);
    }
  }, [pending, status, evidence, language, expanded]);

  const failures = status === "blocked" && evidence
    ? PREFLIGHT_AREAS.filter(area => !evidence.checks[area].ready) : [];
  const confirmedReady = status === "ready" && evidence?.ready === true;
  const retryable = status === "error" || (status === "ready" && !confirmedReady);
  const warning = status === "blocked" ? text("blocked")
    : status === "denied" ? text("denied") : text("unavailable");
  const first = failures[0] || null;

  const actionFor = (area: PreflightArea, path: string | null) => {
    if (!path) return null;
    if (path === "/dispatch") {
      // A Link to the same /dispatch URL does NOTHING when Launch is the
      // selected subtab. This is a real action on the actual workspace.
      const tab: DispatchDestination = area === "zone" ? "zones" : "routes";
      if (!onNavigateToTab || (canNavigateToTab && !canNavigateToTab(tab))) return null;
      return <button type="button" onClick={() => onNavigateToTab(tab)}
        className="inline-flex min-h-8 shrink-0 items-center rounded-md px-2 text-xs font-bold text-amber-900 underline underline-offset-2 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
        {isArabic ? tab === "zones" ? "فتح المناطق" : "عرض الخطوط النشطة"
          : tab === "zones" ? "Open zones" : "View active routes"}
      </button>;
    }
    const label = isArabic
      ? path === "/inventory" ? "فتح المستودع" : path === "/products" ? "فتح المنتجات"
        : path === "/representatives-vehicles" ? "فتح جهات التشغيل"
          : path === "/commercial-rules" ? "فتح القواعد التجارية" : "فتح الإعداد"
      : path === "/inventory" ? "Open inventory" : path === "/products" ? "Open products"
        : path === "/representatives-vehicles" ? "Open operations"
          : path === "/commercial-rules" ? "Open commercial rules" : "Open settings";
    return <Link to={path}
      className="inline-flex min-h-8 shrink-0 items-center rounded-md px-2 text-xs font-bold text-amber-900 underline underline-offset-2 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
      {label}
    </Link>;
  };

  return <section ref={frameRef} data-testid="d11-commercial-preflight" dir={isArabic ? "rtl" : "ltr"}
    aria-label={text("title")} aria-busy={status === "loading"}
    className="w-full min-w-0 min-h-6"
    style={pending ? { minHeight: lastVisibleHeightRef.current } : undefined}>
    {pending ? null : confirmedReady ? (
      <div role="status" aria-live="polite" aria-label={text("ready")}
        className="inline-flex max-w-full min-w-0 items-center gap-1.5 py-1 text-xs font-semibold text-emerald-700">
        <CheckCircle2 aria-hidden="true" className="h-4 w-4 shrink-0" />
        <span>{text("review")}</span>
      </div>
    ) : status === "blocked" && evidence && first ? (
      <div role="status" aria-label={warning} className="min-w-0 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-950">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0 text-amber-600" />
          <strong className="shrink-0 text-xs">{isArabic ? "الإطلاق ممنوع" : "Launch blocked"}</strong>
          <span className="min-w-0 flex-1 text-xs">
            {preflightLabel(language, first)}: {preflightReason(language, evidence.checks[first].code).text}
          </span>
          {failures.length === 1 ? actionFor(first, preflightReason(language, evidence.checks[first].code).path) : (
            <button type="button" onClick={() => setExpanded((was) => !was)}
              aria-expanded={expanded} aria-controls="dispatch-preflight-reasons"
              className="inline-flex min-h-8 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-bold text-amber-900 underline underline-offset-2 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
              {isArabic ? `البنود (${failures.length})` : `Issues (${failures.length})`}
              <ChevronDown aria-hidden="true" className={`h-4 w-4 ${expanded ? "rotate-180" : ""}`} />
            </button>
          )}
        </div>
        {expanded && failures.length > 1 && (
          <ul id="dispatch-preflight-reasons" className="mt-2 min-w-0 space-y-1.5 border-t border-amber-200 pt-2">
            {failures.map((area) => {
              const reason = preflightReason(language, evidence.checks[area].code);
              return <li key={area} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                <span className="min-w-0 flex-1">
                  <strong>{preflightLabel(language, area)}: </strong>{reason.text}
                </span>
                {actionFor(area, reason.path)}
              </li>;
            })}
          </ul>
        )}
      </div>
    ) : (
      <div role="status" className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1 font-semibold">{warning}</span>
        {retryable && <button type="button" onClick={onRefresh}
          className="inline-flex min-h-8 items-center gap-1 rounded-md px-2 font-bold underline underline-offset-2 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
          <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
          {text("refresh")}
        </button>}
      </div>
    )}
  </section>;
}
