import 'package:flutter/material.dart';

import '../application/recovery_sync_coordinator.dart';
import 'recovery_strings.dart';

void showRecoverySyncFeedback(
  BuildContext context,
  RecoverySyncResult result,
) {
  final locale = Localizations.localeOf(context).toLanguageTag();
  final (key, color) = switch (result.disposition) {
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
