import 'package:flutter/material.dart';

import '../application/recovery_reader.dart';
import '../application/recovery_snapshot.dart';
import '../application/recovery_sync_coordinator.dart';
import '../data/recovery_data_source.dart';
import '../data/recovery_sync_executor.dart';
import 'recovery_panel.dart';
import 'recovery_status_banner.dart';
import 'recovery_strings.dart';
import 'recovery_sync_feedback.dart';

class RecoveryDashboardScroll extends StatefulWidget {
  const RecoveryDashboardScroll({
    required this.children,
    required this.onAfterSync,
    this.coordinator,
    this.padding = const EdgeInsets.all(16),
    super.key,
  });

  final List<Widget> children;
  final VoidCallback onAfterSync;
  final RecoverySyncCoordinator? coordinator;
  final EdgeInsetsGeometry padding;

  @override
  State<RecoveryDashboardScroll> createState() =>
      _RecoveryDashboardScrollState();
}

class _RecoveryDashboardScrollState
    extends State<RecoveryDashboardScroll> {
  late RecoverySyncCoordinator _coordinator;
  RecoverySnapshot? _snapshot;
  bool _readUnavailable = false;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    _coordinator = widget.coordinator ?? _defaultCoordinator();
    _reloadSnapshot();
  }

  @override
  void didUpdateWidget(covariant RecoveryDashboardScroll oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.coordinator != widget.coordinator &&
        widget.coordinator != null) {
      _coordinator = widget.coordinator!;
      _reloadSnapshot();
    }
  }

  RecoverySyncCoordinator _defaultCoordinator() {
    return RecoverySyncCoordinator(
      reader: RecoveryReader(
        dataSource: LocalRecoveryDataSource(),
      ),
      executor: ExistingSyncRepositoryExecutor(),
    );
  }

  Future<void> _reloadSnapshot() async {
    try {
      final snapshot = await _coordinator.readSnapshot();
      if (!mounted) return;
      setState(() {
        _snapshot = snapshot;
        _readUnavailable = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _readUnavailable = true;
      });
    }
  }

  Future<void> _refresh() async {
    if (_syncing) return;

    setState(() => _syncing = true);
    final messenger = ScaffoldMessenger.of(context);
    final locale = Localizations.localeOf(context).toLanguageTag();
    final loading = messenger.showSnackBar(
      SnackBar(
        content: Row(
          children: [
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                color: Colors.white,
                strokeWidth: 2,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                recoveryString(
                  RecoveryStringKey.syncInProgress,
                  localeCode: locale,
                ),
              ),
            ),
          ],
        ),
        duration: const Duration(days: 1),
      ),
    );

    final result = await _coordinator.synchronize();
    loading.close();

    if (!mounted) return;

    setState(() {
      _syncing = false;
      if (result.snapshot != null) {
        _snapshot = result.snapshot;
        _readUnavailable = false;
      } else {
        _readUnavailable = true;
      }
    });

    showRecoverySyncFeedback(context, result);
    widget.onAfterSync();
  }

  void _openPanel() {
    final snapshot = _snapshot;
    if (snapshot == null || snapshot.isEmpty) return;
    showRecoveryPanel(context, snapshot);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: widget.padding,
        children: [
          RecoveryStatusBanner(
            snapshot: _snapshot,
            readUnavailable: _readUnavailable,
            onTap: _openPanel,
          ),
          ...widget.children,
        ],
      ),
    );
  }
}
