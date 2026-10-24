import 'package:flutter/material.dart';

import '../application/recovery_sync_coordinator.dart';
import 'recovery_strings.dart';
import 'recovery_view_controller.dart';

void showRecoverySyncFeedback(BuildContext context, RecoverySyncResult result) {
  final locale = Localizations.localeOf(context).toLanguageTag();
  final (key, color) =
      result.execution == RecoverySyncExecution.timedOut
          ? (RecoveryStringKey.syncTimedOut, Colors.orange)
          : result.execution == RecoverySyncExecution.transportAmbiguous
          ? (RecoveryStringKey.syncConnectivityUnresolved, Colors.orange)
          : switch (result.disposition) {
            RecoverySyncDisposition.synced => (
              RecoveryStringKey.syncSuccess,
              Colors.green,
            ),
            RecoverySyncDisposition.incomplete => (
              RecoveryStringKey.syncIncomplete,
              Colors.orange,
            ),
            RecoverySyncDisposition.recoveryRequired => (
              RecoveryStringKey.syncRecoveryRequired,
              Colors.red,
            ),
            RecoverySyncDisposition.unresolved => (
              RecoveryStringKey.syncUnresolved,
              Colors.orange,
            ),
          };

  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(recoveryString(key, localeCode: locale)),
      backgroundColor: color,
      duration: const Duration(seconds: 4),
    ),
  );
}

Future<void> refreshRecoveryWithFeedback(
  BuildContext context,
  RecoveryViewController controller,
  VoidCallback onAfterSync,
) async {
  if (controller.syncing) return;
  final messenger = ScaffoldMessenger.of(context);
  final locale = Localizations.localeOf(context).toLanguageTag();
  final hadPendingWork = controller.snapshot?.hasPending == true;
  final loading =
      hadPendingWork
          ? messenger.showSnackBar(
            SnackBar(
              content: Text(
                recoveryString(
                  RecoveryStringKey.syncInProgress,
                  localeCode: locale,
                ),
              ),
              duration: const Duration(days: 1),
            ),
          )
          : null;

  final result = await controller.synchronize();
  loading?.close();
  if (!context.mounted || result == null) return;

  if (hadPendingWork || result.disposition != RecoverySyncDisposition.synced) {
    showRecoverySyncFeedback(context, result);
  }
  onAfterSync();
}
