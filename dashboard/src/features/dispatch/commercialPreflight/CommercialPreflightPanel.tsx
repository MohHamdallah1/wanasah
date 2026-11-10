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
  const failures = evidence
    ? PREFLIGHT_AREAS.filter(area => !evidence.checks[area].ready) : [];
  const text = (key: Parameters<typeof preflightCopy>[1]) =>
    preflightCopy(language, key);
  return (
    <section data-testid="d11-commercial-preflight" dir={isArabic ? "rtl" : "ltr"}
      aria-label={text("title")}
      className="rounded-2xl border border-slate-200 bg-white px-3 py-3 shadow-sm sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-800">{text("title")}</h2>
        <button type="button" onClick={onRefresh} disabled={status === "choose" || status === "loading"}
          className="min-h-11 rounded-xl border border-slate-300 px-3 text-xs font-bold text-slate-700 hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-[#1e87bb] disabled:opacity-50">
          {text("refresh")}
        </button>
      </div>
      <div role="status" aria-live="polite" className="mt-2 text-sm text-slate-700">
        {status === "choose" ? text("choose") :
          status === "loading" ? text("checking") :
          status === "denied" ? text("denied") :
          status === "error" ? text("unavailable") :
          status === "ready" ? text("ready") : text("blocked")}
      </div>
      {status === "blocked" && evidence && (
        <ul className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2" aria-label={text("blocked")}>
          {failures.map(area => {
            const reason = preflightReason(language, evidence.checks[area].code);
            return (
              <li key={area} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
                <p className="font-bold text-amber-950">{preflightLabel(language, area)}</p>
                <p className="mt-1 text-amber-900">{reason.text}</p>
                {reason.path && (
                  <Link to={reason.path} className="mt-2 inline-flex min-h-10 items-center rounded-lg
                    border border-amber-300 bg-white px-3 text-xs font-semibold text-amber-900
                    underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
                    {text("fix")}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
