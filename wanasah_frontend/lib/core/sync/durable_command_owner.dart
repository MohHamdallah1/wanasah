import 'durable_command.dart';

/// Existing durable columns retain their operational Driver locator semantics.
class DurableCommandOwner {
  DurableCommandOwner({required this.companyCode, required this.driverId}) {
    if (companyCode.trim().isEmpty || companyCode == 'null' || driverId <= 0) {
      throw const DurableCommandOwnerException('DURABLE_OWNER_REQUIRED');
    }
  }
  final String companyCode;
  final int driverId;

  static DurableCommandOwner? fromRow(Map<String, dynamic> row) {
    final company = row['owner_company_code'];
    final driver = row['owner_driver_id'];
    if (company is! String || company.trim().isEmpty ||
        company.trim() == 'null' || driver is! int || driver <= 0) return null;
    return DurableCommandOwner(companyCode: company.trim(), driverId: driver);
  }

  void requireSame(DurableCommandOwner other) {
    if (other.companyCode != companyCode || other.driverId != driverId) {
      throw const DurableCommandOwnerException('DURABLE_OWNER_MISMATCH');
    }
  }

  void requireTenant(String tenant) {
    if (companyCode != tenant) {
      throw const DurableCommandOwnerException('DURABLE_OWNER_COMPANY_MISMATCH');
    }
  }

  void requireRows(Iterable<Map<String, dynamic>> rows) {
    for (final row in rows.where(isUnresolvedOfflineCommand)) {
      final owner = fromRow(row);
      if (owner == null) {
        throw const DurableCommandOwnerException('DURABLE_OWNER_UNATTRIBUTED');
      }
      if (owner.companyCode != companyCode || owner.driverId != driverId) {
        throw const DurableCommandOwnerException('DURABLE_OWNER_MISMATCH');
      }
    }
  }
}

class DurableCommandOwnerException implements Exception {
  const DurableCommandOwnerException(this.code);
  final String code;
  @override
  String toString() => 'DurableCommandOwnerException($code)';
}
