import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../application/recovery_sync_coordinator.dart';
import 'recovery_panel.dart';
import 'recovery_strings.dart';
import 'recovery_sync_feedback.dart';
import 'recovery_view_controller.dart';

enum RecoveryServiceState { available, cached, unreachable, serviceFailure }

/// A compact entry into existing Recovery evidence, not another sync engine.
/// Empty local evidence means "no pending work", never a claim of connectivity.
class RecoveryStatusUtility extends StatelessWidget {
  const RecoveryStatusUtility({
    required this.controller,
    required this.serviceState,
    required this.onAfterSync,
    super.key,
  });

  final RecoveryViewController controller;
  final RecoveryServiceState serviceState;
  final VoidCallback onAfterSync;

  RecoveryStringKey get statusKey {
    if (controller.snapshot?.hasBlocked == true) {
      return RecoveryStringKey.blockedCompact;
    }
    if (controller.readUnavailable) return RecoveryStringKey.unavailableCompact;
    if (controller.syncing) return RecoveryStringKey.syncingCompact;
    if (controller.snapshot?.hasPending == true) {
      return RecoveryStringKey.pendingCompact;
    }
    if (controller.reading || controller.snapshot == null) {
      return RecoveryStringKey.checking;
    }
    if (serviceState == RecoveryServiceState.serviceFailure) {
      return RecoveryStringKey.serviceCompact;
    }
    if (serviceState == RecoveryServiceState.unreachable) {
      return RecoveryStringKey.unreachableCompact;
    }
    if (controller.lastExecution != null &&
        controller.lastExecution != RecoverySyncExecution.completed) {
      return RecoveryStringKey.unavailableCompact;
    }
    if (serviceState == RecoveryServiceState.cached) {
      return RecoveryStringKey.cachedCompact;
    }
    return RecoveryStringKey.noPending;
  }

  String _text(BuildContext context, RecoveryStringKey key) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final count =
        key == RecoveryStringKey.blockedCompact
            ? controller.snapshot?.blockedCount ?? 0
            : controller.snapshot?.pendingCount ?? 0;
    return recoveryString(
      key,
      localeCode: locale,
      values: {'count': NumberFormat.decimalPattern(locale).format(count)},
    );
  }

  bool get _degraded =>
      serviceState == RecoveryServiceState.unreachable ||
      serviceState == RecoveryServiceState.serviceFailure ||
      (controller.lastExecution != null &&
          controller.lastExecution != RecoverySyncExecution.completed);

  IconData get _icon => switch (statusKey) {
    RecoveryStringKey.blockedCompact => Icons.error_outline_rounded,
    RecoveryStringKey.pendingCompact => Icons.schedule_rounded,
    RecoveryStringKey.noPending => Icons.cloud_done_outlined,
    RecoveryStringKey.syncingCompact => Icons.sync_rounded,
    RecoveryStringKey.checking => Icons.more_horiz_rounded,
    _ => Icons.cloud_off_outlined,
  };

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final colors = Theme.of(context).colorScheme;
        final attention = controller.snapshot?.hasBlocked == true;
        return Semantics(
          liveRegion: true,
          child: TextButton(
            key: const ValueKey('shell-sync-status'),
            onPressed: () => _showStatus(context),
            style: TextButton.styleFrom(
              foregroundColor: attention ? colors.error : colors.onSurface,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              alignment: AlignmentDirectional.centerStart,
              minimumSize: const Size(48, 48),
            ),
            child: Row(
              children: [
                Icon(_icon, size: 20),
                const SizedBox(width: 8),
                Expanded(child: Text(_text(context, statusKey))),
                if (_degraded)
                  const Padding(
                    padding: EdgeInsetsDirectional.only(start: 4),
                    child: Icon(Icons.cloud_off_outlined, size: 16),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showStatus(BuildContext thisContext) {
    showModalBottomSheet<void>(
      context: thisContext,
      isScrollControlled: true,
      showDragHandle: true,
      builder:
          (sheetContext) => SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
              child: ListenableBuilder(
                listenable: controller,
                builder: (context, _) {
                  final snapshot = controller.snapshot;
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        _text(context, RecoveryStringKey.panelTitle),
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 12),
                      Text(_text(context, statusKey)),
                      if (controller.readUnavailable)
                        Text(_text(context, RecoveryStringKey.readUnavailable)),
                      if (snapshot?.hasPending == true)
                        Text(_text(context, RecoveryStringKey.pendingCompact)),
                      if (snapshot?.hasBlocked == true)
                        Text(_text(context, RecoveryStringKey.blockedCompact)),
                      if (serviceState != RecoveryServiceState.available)
                        Text(
                          _text(context, switch (serviceState) {
                            RecoveryServiceState.unreachable =>
                              RecoveryStringKey.unreachableCompact,
                            RecoveryServiceState.serviceFailure =>
                              RecoveryStringKey.serviceCompact,
                            _ => RecoveryStringKey.cachedCompact,
                          }),
                        ),
                      if (controller.lastExecution != null &&
                          controller.lastExecution !=
                              RecoverySyncExecution.completed)
                        Text(_text(context, RecoveryStringKey.syncUnresolved)),
                      const SizedBox(height: 16),
                      if (snapshot != null && !snapshot.isEmpty)
                        OutlinedButton(
                          onPressed: () {
                            Navigator.of(sheetContext).pop();
                            showRecoveryPanel(thisContext, snapshot);
                          },
                          child: Text(
                            _text(context, RecoveryStringKey.detailsAction),
                          ),
                        ),
                      TextButton(
                        onPressed:
                            controller.syncing || controller.reading
                                ? null
                                : controller.reload,
                        child: Text(
                          _text(context, RecoveryStringKey.inspectAction),
                        ),
                      ),
                      ElevatedButton.icon(
                        onPressed:
                            controller.syncing
                                ? null
                                : () {
                                  Navigator.of(sheetContext).pop();
                                  refreshRecoveryWithFeedback(
                                    thisContext,
                                    controller,
                                    onAfterSync,
                                  );
                                },
                        icon: const Icon(Icons.sync_rounded),
                        label: Text(
                          _text(context, RecoveryStringKey.refreshAction),
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
          ),
    );
  }
}
