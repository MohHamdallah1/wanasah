class StoredAuthIdentity {
  const StoredAuthIdentity({
    required this.token,
    required this.driverId,
    required this.companyCode,
  });

  final String token;
  final int driverId;
  final String companyCode;

  static StoredAuthIdentity? tryParse({
    required String? token,
    required String? driverId,
    required String? companyCode,
  }) {
    final normalizedToken = token?.trim();
    final normalizedCompanyCode = companyCode?.trim();
    final parsedDriverId = int.tryParse(driverId?.trim() ?? '');

    if (normalizedToken == null ||
        normalizedToken.isEmpty ||
        normalizedCompanyCode == null ||
        normalizedCompanyCode.isEmpty ||
        parsedDriverId == null ||
        parsedDriverId <= 0) {
      return null;
    }

    return StoredAuthIdentity(
      token: normalizedToken,
      driverId: parsedDriverId,
      companyCode: normalizedCompanyCode,
    );
  }
}
