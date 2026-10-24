import 'package:flutter/foundation.dart';

import '../application/recovery_reader.dart';
import '../application/recovery_snapshot.dart';
import '../application/recovery_sync_coordinator.dart';
import '../data/recovery_data_source.dart';
import '../data/recovery_sync_executor.dart';

/// One presentation snapshot for the shell and Home. All durable decisions,
/// persistence and replay remain in the existing Recovery coordinator.
class RecoveryViewController extends ChangeNotifier {
  RecoveryViewController({RecoverySyncCoordinator? coordinator})
    : _coordinator = coordinator ?? RecoverySyncCoordinator(
        reader: RecoveryReader(dataSource: LocalRecoveryDataSource()),
        executor: ExistingSyncRepositoryExecutor(),
      );

  final RecoverySyncCoordinator _coordinator;
  RecoverySnapshot? snapshot;
  RecoverySyncExecution? lastExecution;
  bool readUnavailable = false;
  bool reading = false;
  bool syncing = false;
  bool _disposed = false;
  int _readEpoch = 0;

  Future<void> reload() async {
    if (_disposed || syncing) return;
    final epoch = ++_readEpoch;
    reading = true;
    notifyListeners();
    try {
      final next = await _coordinator.readSnapshot();
      if (_disposed || epoch != _readEpoch) return;
      snapshot = next;
      readUnavailable = false;
    } catch (_) {
      if (_disposed || epoch != _readEpoch) return;
      // Preserve the last known blocked/pending evidence on inspection failure.
      readUnavailable = true;
    }
    if (_disposed || epoch != _readEpoch) return;
    reading = false;
    notifyListeners();
  }

  Future<RecoverySyncResult?> synchronize() async {
    if (_disposed || syncing) return null;
    ++_readEpoch;
    reading = false;
    syncing = true;
    notifyListeners();
    final result = await _coordinator.synchronize();
    if (_disposed) return result;
    syncing = false;
    lastExecution = result.execution;
    readUnavailable = result.snapshot == null;
    snapshot = result.snapshot ?? snapshot;
    notifyListeners();
    return result;
  }

  @override
  void dispose() {
    _disposed = true;
    ++_readEpoch;
    super.dispose();
  }
}
