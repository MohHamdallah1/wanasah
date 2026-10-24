import 'package:flutter/material.dart';

import '../application/recovery_sync_coordinator.dart';
import 'recovery_panel.dart';
import 'recovery_status_banner.dart';
import 'recovery_sync_feedback.dart';
import 'recovery_view_controller.dart';

class RecoveryDashboardScroll extends StatefulWidget {
  const RecoveryDashboardScroll({
    required this.children,
    required this.onAfterSync,
    this.coordinator,
    this.controller,
    this.padding = const EdgeInsets.all(16),
    super.key,
  }) : assert(coordinator == null || controller == null);

  final List<Widget> children;
  final VoidCallback onAfterSync;
  final RecoverySyncCoordinator? coordinator;
  final RecoveryViewController? controller;
  final EdgeInsetsGeometry padding;

  @override
  State<RecoveryDashboardScroll> createState() => _RecoveryDashboardScrollState();
}

class _RecoveryDashboardScrollState extends State<RecoveryDashboardScroll> {
  late RecoveryViewController _controller;
  late bool _ownsController;

  @override
  void initState() {
    super.initState();
    _attach();
  }

  void _attach() {
    _ownsController = widget.controller == null;
    _controller = widget.controller ??
        RecoveryViewController(coordinator: widget.coordinator);
    if (_ownsController) _controller.reload();
  }

  @override
  void didUpdateWidget(covariant RecoveryDashboardScroll oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller ||
        oldWidget.coordinator != widget.coordinator) {
      if (_ownsController) _controller.dispose();
      _attach();
    }
  }

  @override
  void dispose() {
    if (_ownsController) _controller.dispose();
    super.dispose();
  }

  void _openPanel() {
    final snapshot = _controller.snapshot;
    if (snapshot == null || snapshot.isEmpty) return;
    showRecoveryPanel(context, snapshot);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _controller,
      builder: (context, _) => RefreshIndicator(
        onRefresh: () => refreshRecoveryWithFeedback(
          context, _controller, widget.onAfterSync,
        ),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: widget.padding,
          children: [
            RecoveryStatusBanner(
              snapshot: _controller.snapshot,
              readUnavailable: _controller.readUnavailable,
              onTap: _openPanel,
            ),
            ...widget.children,
          ],
        ),
      ),
    );
  }
}
