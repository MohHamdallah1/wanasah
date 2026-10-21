class StoredAuthIdentity {
  const StoredAuthIdentity({
    required this.token,
    required this.refreshToken,
    required this.driverId,
    required this.companyCode,
  });

  final String token;
  final String refreshToken;
  final int driverId;
  final String companyCode;

  static StoredAuthIdentity? tryParse({
    required String? token,
    required String? refreshToken,
    required String? driverId,
    required String? companyCode,
  }) {
    final normalizedToken = token?.trim();
    final normalizedRefreshToken = refreshToken?.trim();
    final normalizedCompanyCode = companyCode?.trim();
    final parsedDriverId = int.tryParse(driverId?.trim() ?? '');

    if (normalizedToken == null ||
        normalizedToken.isEmpty ||
        normalizedToken == 'null' ||
        normalizedRefreshToken == null ||
        normalizedRefreshToken.isEmpty ||
        normalizedRefreshToken == 'null' ||
        normalizedCompanyCode == null ||
        normalizedCompanyCode.isEmpty ||
        normalizedCompanyCode == 'null' ||
        parsedDriverId == null ||
        parsedDriverId <= 0) {
      return null;
    }

    return StoredAuthIdentity(
      token: normalizedToken,
      refreshToken: normalizedRefreshToken,
      driverId: parsedDriverId,
      companyCode: normalizedCompanyCode,
    );
  }
}
