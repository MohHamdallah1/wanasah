// Pure request contract shared by the ledger list, reference modal and tests.
// No React/Auth/env import: this must be testable with no Dashboard bootstrap.
export const buildLedgerCursorUrl = ({
  locationId,
  cursor,
  search,
  referenceType,
  referenceId,
  limit = PAGE_SIZE,
}: {
  locationId: number;
  cursor?: string | null;
  search?: string;
  referenceType?: string;
  referenceId?: string;
  limit?: number;
}): string => {
  const params = new URLSearchParams({
    location_id: String(locationId),
    limit: String(limit),
  });
  if (cursor) params.set("cursor", cursor);
  if (referenceId) {
    params.set("reference_id", referenceId);
    if (referenceType) params.set("reference_type", referenceType);
  } else {
    const cleanSearch = (search ?? "").trim();
    if (cleanSearch.length >= 2) params.set("search", cleanSearch);
    if (referenceType && referenceType !== "ALL") params.set("reference_type", referenceType);
  }
  return `/warehouse/ledger/cursor?${params.toString()}`;
};
