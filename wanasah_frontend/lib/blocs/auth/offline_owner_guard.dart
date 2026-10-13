enum OfflineOwnerLoginDecision {
  sameOwner,
  differentDriverSameCompany,
  differentCompany,
  noOwner,
}

OfflineOwnerLoginDecision classifyOfflineOwnerLogin({
  required String? ownerCompanyCode,
  required String? ownerDriverId,
  required String returnedCompanyCode,
  required int returnedDriverId,
}) {
  final companyCode = ownerCompanyCode?.trim();
  final driverId = int.tryParse(ownerDriverId?.trim() ?? '');

  if (companyCode == null || companyCode.isEmpty || driverId == null || driverId <= 0) {
    return OfflineOwnerLoginDecision.noOwner;
  }
  if (companyCode != returnedCompanyCode) {
    return OfflineOwnerLoginDecision.differentCompany;
  }
  if (driverId != returnedDriverId) {
    return OfflineOwnerLoginDecision.differentDriverSameCompany;
  }
  return OfflineOwnerLoginDecision.sameOwner;
}
