export function productDraftStorageKey(
  companyId: number | null,
  driverId: number | null,
) {
  return companyId && driverId
    ? `wanasah:product-draft:v2:${companyId}:${driverId}`
    : null;
}
