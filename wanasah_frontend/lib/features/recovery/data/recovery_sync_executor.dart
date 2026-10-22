import '../../../repositories/sync_repository.dart';

abstract interface class RecoverySyncExecutor {
  Future<bool> synchronize();
}

class ExistingSyncRepositoryExecutor implements RecoverySyncExecutor {
  ExistingSyncRepositoryExecutor({SyncRepository? repository})
      : _repository = repository ?? SyncRepository();

  final SyncRepository _repository;

  @override
  Future<bool> synchronize() => _repository.syncDown();
}
