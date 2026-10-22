import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../blocs/dashboard/dashboard_event.dart';
import '../blocs/dashboard/dashboard_state.dart';
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import 'visit_list_screen.dart';
import '../features/work_session/presentation/work_session_controls.dart';
import '../features/recovery/presentation/recovery_dashboard_scroll.dart';
import '../features/custody/presentation/pending_transfer_dialog.dart';
import '../features/custody/presentation/vehicle_inventory_section.dart';


class DashboardScreen extends StatefulWidget {
  final int driverId;
  const DashboardScreen({required this.driverId, super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  // Recovery safety invariant: blocked evidence is durable؛ لا يمكن حذفها من تطبيق المندوب.
  // +++ الشاشة الآن "غبية" وتعتمد على الـ BLoC بنسبة 100% +++
  bool _isShowingDialog = false; // لمنع تكرار ظهور نافذة الحوالات
  bool _isActionInProgress = false; // +++ درع منع النقر المتكرر أثناء طلبات الـ API والموقع +++

  @override
  void initState() {
    super.initState();
    // 1. عرض البيانات المحلية فوراً كـ Cache (نصيحة الصديق لتسريع الشاشة)
    context.read<DashboardBloc>().add(const LoadDashboardData());
    // 2. إعطاء الأمر للعقل المدبر بجلب البيانات الحية من السيرفر
    context.read<DashboardBloc>().add(
      FetchDashboardData(driverId: widget.driverId),
    );
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
              child: const Text('إلغاء'),
              onPressed: () => Navigator.of(dialogContext).pop(false),
            ),
            TextButton(
              child: const Text('نعم، تأكيد'),
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
      'تأكيد الخروج',
      'هل تريد تسجيل الخروج؟',
    );
    if (confirmed == true) {
      if (!mounted) return; // +++ الدرع الواقي للـ BuildContext +++
      context.read<AuthBloc>().add(const LogoutEvent());
    }
  }

  // --- نافذة الحوالات المعلقة: العرض في Custody، والحدث يبقى في Dashboard shell ---
  Future<void> _showTransferDialog(
    BuildContext context,
    Map<String, dynamic> batchData,
  ) async {
    final result = await showPendingTransferDialog(context, batchData);
    if (!context.mounted) return;

    _isShowingDialog = false;

    switch (result.disposition) {
      case PendingTransferDialogDisposition.empty:
        context.read<DashboardBloc>().add(
          const RespondToBatchTransfer(
            transferIds: [],
            responseStatus: 'ignored',
            detailedTransfers: [],
          ),
        );
        return;
      case PendingTransferDialogDisposition.deferred:
        return;
      case PendingTransferDialogDisposition.submitted:
        context.read<DashboardBloc>().add(
          RespondToBatchTransfer(
            transferIds: const [],
            responseStatus: 'mixed',
            detailedTransfers: result.detailedResponses,
          ),
        );
        return;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // +++  لظاهرة الأشباح: لون صلب يمنع الشفافية +++
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        backgroundColor: Colors.grey.shade50,
        elevation: 0,
        title: const Text('اللوحة الرئيسية'),
        centerTitle: true,
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            onPressed:
                () => context.read<DashboardBloc>().add(
                  FetchDashboardData(driverId: widget.driverId),
                ),
            icon: const Icon(Icons.refresh),
            tooltip: 'تحديث البيانات',
          ),
          BlocBuilder<DashboardBloc, DashboardState>(
            builder: (context, state) {
              return IconButton(
                icon: const Icon(Icons.logout),
                tooltip: 'تسجيل الخروج',
                onPressed: _logout, // +++ السماح بالخروج دائماً وتجنب فخ الأوفلاين +++
              );
            },
          ),
        ],
      ),
      // +++ هنا يتجلى ذكاء الـ MultiBlocListener لربط التطبيق ككتلة واحدة +++
      body: MultiBlocListener(
        listeners: [
          BlocListener<DashboardBloc, DashboardState>(
            listener: (context, state) {
              // +++  (البند 6): تحرير القفل فقط عند صدور نتيجة حقيقية للعملية لمنع السباق +++
              if (state is DashboardError || (state is DashboardLoaded && state.actionSuccessMessage != null)) {
                if (_isActionInProgress && mounted) {
                  setState(() => _isActionInProgress = false);
                }
              }

              if (state is DashboardError) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(state.message),
                    backgroundColor: Colors.red,
                  ),
                );
              } else if (state is DashboardLoaded) {
                // +++   اصطياد رسائل النجاح المدمجة بالـ State بدون تدمير الشجرة +++
                if (state.actionSuccessMessage != null) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(state.actionSuccessMessage!),
                      backgroundColor: state.actionSuccessMessage!.contains('🧹') ? Colors.orange : Colors.green,
                    ),
                  );
                  // تنظيف الرسالة فور عرضها كي لا تظهر مرة أخرى عند إعادة البناء
                  context.read<DashboardBloc>().add(const ClearActionMessageEvent());
                }

                // تزامن الواجهة مع البلوك لظهور الحوالة
                // تزامن الواجهة مع البلوك لظهور الحوالة
                if (state.pendingTransfer != null && !_isShowingDialog) {
                  _isShowingDialog = true;
                  _showTransferDialog(context, state.pendingTransfer!);
                }
              }
            },
          ),
        ],
        child: BlocBuilder<DashboardBloc, DashboardState>(
          builder: (context, state) {
            // +++ السطر الذي نسيته وتسبب في كسر الشجرة +++
            if (state is DashboardLoading || state is DashboardInitial) {
              return const Center(child: CircularProgressIndicator());
            } else if (state is DashboardLoaded) {
              return _buildDashboardContent(state); // تمرير البيانات للشاشة
            } else if (state is DashboardError) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        'حدث خطأ: ${state.message}',
                        style: const TextStyle(color: Colors.red),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 10),
                      ElevatedButton(
                        onPressed:
                            () => context.read<DashboardBloc>().add(
                              FetchDashboardData(driverId: widget.driverId),
                            ),
                        child: const Text('إعادة المحاولة'),
                      ),
                    ],
                  ),
                ),
              );
            }
            return const SizedBox.shrink();
          },
        ),
      ),
    );
  }
  
  // --- دالة بناء المحتوى: Recovery يملك القراءة/المزامنة/العرض، والداشبورد يركّب المحتوى فقط. ---
  Widget _buildDashboardContent(DashboardLoaded state) {
    return RecoveryDashboardScroll(
      onAfterSync: () {
        if (!mounted) return;
        context.read<DashboardBloc>().add(const LoadDashboardData());
      },
      children: [
          // تنبيه بوضع الأوفلاين
          if (state.isOffline)
            Container(
              padding: const EdgeInsets.all(8),
              margin: const EdgeInsets.only(bottom: 10), // التعديل الصحيح
              color: Colors.orange.shade100,
              child: const Row(
                children: [
                  Icon(Icons.wifi_off, color: Colors.orange),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'أنت في وضع عدم الاتصال. يتم عرض البيانات المحلية.',
                      style: TextStyle(
                        color: Colors.deepOrange,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
            ),

          Text(
            'أهلاً بك، ${state.driverName}!',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            'المنطقة المخصصة: ${state.assignedRegion}',
            style: TextStyle(fontSize: 17, color: Colors.blueGrey[700]),
          ),
          const SizedBox(height: 8),
          Text(
            'تاريخ اليوم: ${DateTime.now().year}-${DateTime.now().month.toString().padLeft(2, '0')}-${DateTime.now().day.toString().padLeft(2, '0')}',
            style: TextStyle(fontSize: 15, color: Colors.grey[600]),
          ),
          const Divider(height: 30, thickness: 1),

          WorkSessionControls(
            isActiveSession: state.isActiveSession,
            activeSessionStartTime: state.activeSessionStartTime,
            isOnBreak: state.isOnBreak,
            isActionInProgress: _isActionInProgress,
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
          const Divider(height: 30, thickness: 1),
          Text('ملخص الجولة:', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Text(
            ' - الزيارات المكتملة: ${state.completedVisits}',
            style: const TextStyle(fontSize: 16),
          ),
          Text(
            ' - الزيارات الناجحة (مبيعات): ${state.salesInCompleted}',
            style: const TextStyle(fontSize: 16),
          ),
          Text(
            ' - الزيارات المعلقة: ${state.pendingVisits}',
            style: const TextStyle(fontSize: 16),
          ),
          if (state.offlineVisits > 0)
            Text(
              ' - بانتظار المزامنة 🔴: ${state.offlineVisits}',
              style: const TextStyle(
                fontSize: 16,
                color: Colors.red,
                fontWeight: FontWeight.bold,
              ),
            ),

          const SizedBox(height: 15),
          Text('الملخص المالي:', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'إجمالي كاش المبيعات: ${state.totalSalesCash.toStringAsFixed(3)} د.أ',
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  'إجمالي الذمم المحصلة: (${state.debtPaymentsCount}) ${state.totalDebtPaid.toStringAsFixed(3)} د.أ',
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  'إجمالي الكاش المستلم: ${state.totalCashOverall.toStringAsFixed(3)} د.أ',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 10),
          Center(
            child: ElevatedButton.icon(
              icon: const Icon(Icons.list_alt_rounded),
              label: const Text('عرض قائمة زيارات اليوم'),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder:
                        (context) => VisitListScreen(driverId: widget.driverId),
                  ),
                ).then((_) {
                  if (mounted) {
                    context.read<DashboardBloc>().add(
                      FetchDashboardData(driverId: widget.driverId),
                    );
                  }
                });
              },
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 30,
                  vertical: 15,
                ),
                textStyle: const TextStyle(fontSize: 16),
              ),
            ),
          ),

          VehicleInventorySection(products: state.products),
        ],
    );
  }
}