import '../../../core/db/local_database.dart';

abstract interface class RecoveryDataSource {
  Future<List<Map<String, dynamic>>> readUnresolvedRows();
}

class LocalRecoveryDataSource implements RecoveryDataSource {
  LocalRecoveryDataSource({LocalDatabase? database})
      : _database = database ?? LocalDatabase.instance;

  final LocalDatabase _database;

  @override
  Future<List<Map<String, dynamic>>> readUnresolvedRows() {
    return _database.getPendingSyncs();
  }
}
