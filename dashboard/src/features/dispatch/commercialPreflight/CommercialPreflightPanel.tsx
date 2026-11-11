import { AlertTriangle, CheckCircle2, RotateCcw } from "lucide-react";
import { Link } from "react-router-dom";
import {
  PREFLIGHT_AREAS, preflightCopy, preflightLabel, preflightReason,
  type CommercialPreflight,
} from "./contract";

export function CommercialPreflightPanel({
  language, status, evidence, onRefresh,
}: {
  language: string;
  status: "choose" | "loading" | "denied" | "error" | "ready" | "blocked";
  evidence: CommercialPreflight | null;
  onRefresh: () => void;
}) {
  const isArabic = language.toLowerCase().startsWith("ar");
  const text = (key: Parameters<typeof preflightCopy>[1]) =>
    preflightCopy(language, key);

  // The real readiness slot always reserves its single-line footprint. A
  // background signed read must never insert a temporary line or expose approval.

  const failures = status === "blocked" && evidence
    ? PREFLIGHT_AREAS.filter(area => !evidence.checks[area].ready) : [];
  // Display success only for an actual positive advisory from the caller.
  // Launch authorization and the fresh pre-POST read remain in the existing hook.
  const confirmedReady = status === "ready" && evidence?.ready === true;
  // Blocked evidence is rechecked automatically while the launch tab is visible.
  // Manual recovery is only for a failed read, never an extra launch step.
  const retryable = status === "error" || (status === "ready" && !confirmedReady);
  const warning = status === "blocked" ? text("blocked")
    : status === "denied" ? text("denied") : text("unavailable");

  return (
    <section data-testid="d11-commercial-preflight" dir={isArabic ? "rtl" : "ltr"}
      aria-label={text("title")} aria-busy={status === "loading"}
      className="w-full min-w-0 min-h-6">
      {status === "loading" || status === "choose" ? null : confirmedReady ? (
        <div role="status" aria-live="polite" aria-label={text("ready")}
          className="inline-flex max-w-full min-w-0 items-center gap-1.5 py-1 text-xs font-semibold text-emerald-700">
          <CheckCircle2 aria-hidden="true" className="h-4 w-4 shrink-0" />
          <span>{text("review")}</span>
        </div>
      ) : (
        <div role="status" aria-live="polite"
          className="min-w-0 space-y-1.5 py-1 text-xs text-amber-900">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
            <div className="flex min-w-0 items-start gap-2">
              <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <span className="min-w-0 break-words font-semibold">{warning}</span>
            </div>
            {retryable && (
              <button type="button" onClick={onRefresh}
                className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md px-2 text-xs font-semibold text-amber-900 underline underline-offset-2 hover:bg-amber-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
                <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
                {text("refresh")}
              </button>
            )}
          </div>
          {status === "blocked" && evidence && failures.length > 0 && (
            <ul className="min-w-0 space-y-1.5 ps-6" aria-label={text("blocked")}>
              {failures.map(area => {
                const reason = preflightReason(language, evidence.checks[area].code);
                return (
                  <li key={area} className="min-w-0 break-words">
                    <span className="font-semibold">{preflightLabel(language, area)}: </span>
                    <span>{reason.text}</span>
                    {reason.path && (
                      <Link to={reason.path}
                        className="ms-2 inline-flex min-h-9 items-center rounded-md px-1 font-semibold underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
                        {text("fix")}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
