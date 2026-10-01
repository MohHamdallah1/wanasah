import { productDurableScope } from "@/pages/products/productDurableScope";

export type CorrectionRoute = "inline" | "file";

/**
 * File and cell correction share one job and one mutation authority.
 * Never submit a second, different correction while another route has
 * an unresolved request or the user has uncommitted inline cell edits.
 *
 * Reads only scoped operation presence: no file bytes or cell data.
 * Unavailable browser storage is treated as unsafe, not as an empty scope.
 */
export function correctionRouteBlocked(
  companyId: number | null,
  driverId: number | null,
  jobId: string | null,
  route: CorrectionRoute,
): boolean {
  if (!companyId || !driverId || !jobId) return true;
  const fileScope = productDurableScope(
    companyId, driverId, "product-import-correction", jobId,
  );
  const inlineScope = productDurableScope(
    companyId, driverId, "product-import-inline-correction", jobId,
  );
  try {
    return route === "file"
      ? localStorage.getItem(inlineScope) !== null ||
          sessionStorage.getItem(inlineScope + ":draft") !== null
      : localStorage.getItem(fileScope) !== null;
  } catch {
    return true;
  }
}

export function hasUnresolvedCorrectionWork(
  companyId: number | null,
  driverId: number | null,
  jobId: string | null,
): boolean {
  if (!companyId || !driverId || !jobId) return false;
  const fileScope = productDurableScope(
    companyId, driverId, "product-import-correction", jobId,
  );
  const inlineScope = productDurableScope(
    companyId, driverId, "product-import-inline-correction", jobId,
  );
  try {
    return localStorage.getItem(fileScope) !== null ||
      localStorage.getItem(inlineScope) !== null ||
      sessionStorage.getItem(inlineScope + ":draft") !== null;
  } catch {
    return true;
  }
}
