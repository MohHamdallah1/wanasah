import 'recovery_command.dart';

class RecoverySnapshot {
  const RecoverySnapshot({
    required this.commands,
  });

  const RecoverySnapshot.empty() : commands = const <RecoveryCommand>[];

  final List<RecoveryCommand> commands;

  List<RecoveryCommand> get pending => List<RecoveryCommand>.unmodifiable(
        commands.where((command) => !command.isBlocked),
      );

  List<RecoveryCommand> get blocked => List<RecoveryCommand>.unmodifiable(
        commands.where((command) => command.isBlocked),
      );

  int get pendingCount => pending.length;
  int get blockedCount => blocked.length;
  bool get isEmpty => commands.isEmpty;
  bool get hasPending => pendingCount > 0;
  bool get hasBlocked => blockedCount > 0;
}
