import '../data/recovery_data_source.dart';
import 'recovery_command.dart';
import 'recovery_snapshot.dart';

class RecoveryReader {
  RecoveryReader({required RecoveryDataSource dataSource})
      : _dataSource = dataSource;

  final RecoveryDataSource _dataSource;

  Future<RecoverySnapshot> read() async {
    final rows = await _dataSource.readUnresolvedRows();
    return RecoverySnapshot(
      commands: List<RecoveryCommand>.unmodifiable(
        rows.map(RecoveryCommand.fromRow),
      ),
    );
  }
}
