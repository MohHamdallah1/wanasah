export function productImportSessionKey(
  companyId: number | null,
  driverId: number | null,
) {
  return companyId && driverId
    ? `wanasah:product-import:v1:${companyId}:${driverId}`
    : null;
}
