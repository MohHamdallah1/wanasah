import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../features/home/presentation/home_overview.dart';
import '../app/shell/field_app_shell.dart';
import '../app/theme/field_theme.dart';
import '../features/recovery/presentation/recovery_view_controller.dart';
import '../features/recovery/application/recovery_sync_coordinator.dart';
import '../features/recovery/presentation/recovery_status_utility.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../blocs/dashboard/dashboard_event.dart';
import '../blocs/dashboard/dashboard_state.dart';
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import 'visit_list_screen.dart';
import '../features/work_session/presentation/work_session_controls.dart';
import '../features/recovery/presentation/recovery_dashboard_scroll.dart';
import '../features/custody/presentation/pending_transfer_dialog.dart';
import '../features/custody/domain/pending_transfer.dart';
import '../features/custody/presentation/vehicle_inventory_section.dart';
import '../app/localization/app_copy.dart';


class DashboardScreen extends StatefulWidget {
  final int driverId;
  const DashboardScreen({required this.driverId, this.recoveryCoordinator, super.key});
  final RecoverySyncCoordinator? recoveryCoordinator;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> with WidgetsBindingObserver {
  late final RecoveryViewController _recovery;
  // Recovery safety invariant: blocked evidence is durable؛ لا يمكن حذفها من تطبيق المندوب.
  // +++ الشاشة الآن "غبية" وتعتمد على الـ BLoC بنسبة 100% +++
  bool _isShowingDialog = false; // لمنع تكرار ظهور نافذة الحوالات
  bool _isActionInProgress = false; // +++ درع منع النقر المتكرر أثناء طلبات الـ API والموقع +++

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _recovery = RecoveryViewController(coordinator: widget.recoveryCoordinator)..reload();
    // 1. عرض البيانات المحلية فوراً كـ Cache (نصيحة الصديق لتسريع الشاشة)
    context.read<DashboardBloc>().add(const LoadDashboardData());
    // 2. إعطاء الأمر للعقل المدبر بجلب البيانات الحية من السيرفر
    context.read<DashboardBloc>().add(
      FetchDashboardData(driverId: widget.driverId),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _recovery.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _recovery.reload();
  }

  void _refreshDashboard() {
    _recovery.reload();
    context.read<DashboardBloc>().add(
      FetchDashboardData(driverId: widget.driverId),
    );
  }

  void _afterLocalWork() {
    _recovery.reload();
    context.read<DashboardBloc>().add(const LoadDashboardData());
  }

  void _destinationChanged(FieldDestination destination) {
    if (destination == FieldDestination.route) {
      _recovery.reload();
    } else {
      _refreshDashboard();
    }
  }

  // --- دالة مساعدة لعرض مربع حوار التأكيد ---
  Future<bool?> _showConfirmationDialog(
    BuildContext context,
    String title,
    String content,
  ) async {
    return await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (BuildContext dialogContext) {
        return AlertDialog(
          title: Text(title),
          content: Text(content),
          actions: <Widget>[
            TextButton(
              child: Text(AppCopy.of(context, AppCopyKey.cancel)),
              onPressed: () => Navigator.of(dialogContext).pop(false),
            ),
            TextButton(
              child: Text(AppCopy.of(context, AppCopyKey.confirm)),
              onPressed: () => Navigator.of(dialogContext).pop(true),
            ),
          ],
        );
      },
    );
  }

  // --- دالة تسجيل الخروج ---
  Future<void> _logout() async {
    final bool? confirmed = await _showConfirmationDialog(
      context,
      AppCopy.of(context, AppCopyKey.logoutTitle),
      AppCopy.of(context, AppCopyKey.logoutPrompt),
    );
    if (confirmed == true) {
      if (!mounted) return; // +++ الدرع الواقي للـ BuildContext +++
      context.read<AuthBloc>().add(const LogoutEvent());
    }
  }

  // --- نافذة الحوالات المعلقة: العرض في Custody، والحدث يبقى في Dashboard shell ---
  Future<void> _showTransferDialog(
    BuildContext context,
    PendingTransferBatch batch,
  ) async {
    final result = await showPendingTransferDialog(context, batch);
    if (!context.mounted) return;

    setState(() => _isShowingDialog = false);

    switch (result.disposition) {
      case PendingTransferDialogDisposition.empty:
        context.read<DashboardBloc>().add(
          const RespondToBatchTransfer(),
        );
        return;
      case PendingTransferDialogDisposition.deferred:
        return;
      case PendingTransferDialogDisposition.submitted:
        context.read<DashboardBloc>().add(
          RespondToBatchTransfer(decisions: result.decisions),
        );
        return;
    }
  }

  @override
  Widget build(BuildContext context) {
    return MultiBlocListener(
        listeners: [
          BlocListener<DashboardBloc, DashboardState>(
            listener: (context, state) {
              // +++  (البند 6): تحرير القفل فقط عند صدور نتيجة حقيقية للعملية لمنع السباق +++
              if (state is DashboardError ||
                  (state is DashboardLoaded &&
                      (state.actionSuccessMessage != null ||
                          state.workSessionIssue != null))) {
                if (_isActionInProgress && mounted) {
                  setState(() => _isActionInProgress = false);
                }
              }

              if (state is DashboardError) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                      AppCopy.of(context, AppCopyKey.dashboardGenericError),
                    ),
                    backgroundColor: Theme.of(context).colorScheme.error,
                  ),
                );
              } else if (state is DashboardLoaded) {
                // +++   اصطياد رسائل النجاح المدمجة بالـ State بدون تدمير الشجرة +++
                if (state.actionSuccessMessage != null) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(state.actionSuccessMessage!),
                      backgroundColor: Theme.of(context).colorScheme.primary,
                    ),
                  );
                  // تنظيف الرسالة فور عرضها كي لا تظهر مرة أخرى عند إعادة البناء
                  context.read<DashboardBloc>().add(const ClearActionMessageEvent());
                }

                // Preserve the existing transfer decision dialog and event path.
                if (state.pendingTransfer != null && !_isShowingDialog) {
                  _isShowingDialog = true;
                  _showTransferDialog(context, state.pendingTransfer!);
                }
              }
            },
          ),
        ],
        child: BlocBuilder<DashboardBloc, DashboardState>(
          builder: (context, state) => FieldAppShell(
            accountName: state is DashboardLoaded ? state.driverName : '',
            statusUtility: RecoveryStatusUtility(
              controller: _recovery,
              serviceState: _serviceState(state),
              onAfterSync: _afterLocalWork,
            ),
            onRefresh: _refreshDashboard,
            onLogout: _logout,
            onDestinationChanged: _destinationChanged,
            homeBuilder: (context, openRoute, openCustody) =>
                _buildHomeState(context, state, openRoute, openCustody),
            routeBuilder: (context) => VisitListScreen(
              driverId: widget.driverId,
              embedded: true,
              onReturnFromAction: _afterLocalWork,
            ),
            custody: Builder(builder: (context) => _buildCustodyState(context, state)),
          ),
        ),
    );
  }

  RecoveryServiceState _serviceState(DashboardState state) {
    if (state is DashboardError) return RecoveryServiceState.serviceFailure;
    if (state is! DashboardLoaded) return RecoveryServiceState.cached;
    if (state.refreshIssue?.kind == DashboardRefreshIssueKind.service) {
      return RecoveryServiceState.serviceFailure;
    }
    if (state.refreshIssue?.kind == DashboardRefreshIssueKind.connectivity) {
      return RecoveryServiceState.unreachable;
    }
    return state.isOffline
        ? RecoveryServiceState.cached : RecoveryServiceState.available;
  }

  Widget _buildHomeState(BuildContext context, DashboardState state,
      VoidCallback openRoute, VoidCallback openCustody) {
            // +++ السطر الذي نسيته وتسبب في كسر الشجرة +++
            if (state is DashboardLoading || state is DashboardInitial) {
              return const Center(child: CircularProgressIndicator());
            } else if (state is DashboardLoaded) {
              return _buildDashboardContent(context, state, openRoute, openCustody); // تمرير البيانات للشاشة
            } else if (state is DashboardError) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        AppCopy.of(context, AppCopyKey.dashboardGenericError),
                        style: TextStyle(color: Theme.of(context).colorScheme.error),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 10),
                      ElevatedButton(
                        onPressed:
                            () => context.read<DashboardBloc>().add(
                              FetchDashboardData(driverId: widget.driverId),
                            ),
                        child: Text(
                          AppCopy.of(context, AppCopyKey.retry),
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }
            return const SizedBox.shrink();
  }

  Widget _pendingTransfers(DashboardLoaded state) {
    if (state.pendingTransfer == null) return const SizedBox.shrink();
    return OutlinedButton.icon(
      onPressed: _isShowingDialog ? null : () {
        _isShowingDialog = true;
        _showTransferDialog(context, state.pendingTransfer!);
      },
      icon: const Icon(Icons.move_to_inbox_outlined),
      label: Text(AppCopy.of(context, AppCopyKey.pendingTransfers)),
    );
  }

  Widget _buildCustodyState(BuildContext context, DashboardState state) {
    if (state is! DashboardLoaded) {
      return _buildHomeState(context, state, () {}, () {});
    }
    return RecoveryDashboardScroll(
      key: const PageStorageKey('field-custody'),
      controller: _recovery,
      onAfterSync: _afterLocalWork,
      padding: const EdgeInsets.all(FieldTheme.gutter),
      children: [
        if (state.refreshIssue != null) _buildRefreshIssueBanner(context, state.refreshIssue!),
        _pendingTransfers(state),
        VehicleInventorySection(
          products: state.products,
          nonSellableCustody: state.nonSellableCustody,
          pendingReturnCustody: state.pendingReturnCustody,
        ),
      ],
    );
  }

  Widget _buildRefreshIssueBanner(BuildContext context, DashboardRefreshIssue issue) {
    final isConnectivity =
        issue.kind == DashboardRefreshIssueKind.connectivity;
    final messageKey =
        isConnectivity
            ? AppCopyKey.dashboardConnectivityCached
            : AppCopyKey.dashboardServiceCached;

    return Container(
      padding: const EdgeInsets.all(12),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            isConnectivity ? Icons.cloud_off_rounded : Icons.cloud_sync_rounded,
            color: Theme.of(context).colorScheme.onSurface,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              AppCopy.of(context, messageKey),
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurface,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // --- دالة بناء المحتوى: Recovery يملك القراءة/المزامنة/العرض، والداشبورد يركّب المحتوى فقط. ---
  Widget _buildDashboardContent(BuildContext context, DashboardLoaded state,
      VoidCallback openRoute, VoidCallback openCustody) {
    return RecoveryDashboardScroll(
      key: const PageStorageKey('field-home'),
      controller: _recovery,
      onAfterSync: _afterLocalWork,
      padding: const EdgeInsets.all(FieldTheme.gutter),
      children: [
        if (state.refreshIssue != null) _buildRefreshIssueBanner(context, state.refreshIssue!),
        HomeOverview(
          state: state,
          openRoute: openRoute,
          openCustody: openCustody,
          pendingTransfers: _pendingTransfers(state),
          workSession: WorkSessionControls(
            isActiveSession: state.isActiveSession,
            activeSessionStartTime: state.activeSessionStartTime,
            isOnBreak: state.isOnBreak,
            isActionInProgress: _isActionInProgress,
            issue: state.workSessionIssue,
            onActionStarted: () {
              if (mounted) {
                setState(() => _isActionInProgress = true);
              }
            },
            onStart: () {
              context.read<DashboardBloc>().add(
                StartSessionEvent(driverId: widget.driverId),
              );
            },
            onEnd: () {
              context.read<DashboardBloc>().add(
                EndSessionEvent(driverId: widget.driverId),
              );
            },
            onToggleBreak: (action) {
              context.read<DashboardBloc>().add(
                ToggleBreakEvent(
                  driverId: widget.driverId,
                  action: action,
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}
