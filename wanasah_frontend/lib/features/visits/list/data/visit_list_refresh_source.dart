import '../../../../core/db/local_database.dart';
import '../../../../repositories/sync_repository.dart';

abstract interface class VisitListRefreshSource {
  Future<bool> syncDown();
  Future<List<Map<String, dynamic>>> readUnresolvedCommands();
}

class CompatibilityVisitListRefreshSource
    implements VisitListRefreshSource {
  CompatibilityVisitListRefreshSource({
    SyncRepository? syncRepository,
    LocalDatabase? database,
  }) : _syncRepository = syncRepository ?? SyncRepository(),
       _database = database ?? LocalDatabase.instance;

  final SyncRepository _syncRepository;
  final LocalDatabase _database;

  @override
  Future<bool> syncDown() => _syncRepository.syncDown();

  @override
  Future<List<Map<String, dynamic>>> readUnresolvedCommands() {
    return _database.getPendingSyncs();
  }
}
