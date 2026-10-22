import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../blocs/dashboard/dashboard_event.dart';
import '../blocs/dashboard/dashboard_state.dart';
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import 'visit_list_screen.dart';
import 'dart:async';
import 'dart:developer' as developer; 
import '../core/db/local_database.dart';
import '../features/work_session/presentation/work_session_controls.dart';
import '../features/custody/presentation/pending_transfer_dialog.dart';
import '../features/custody/domain/pending_transfer.dart';
import '../features/custody/presentation/vehicle_inventory_section.dart';
import 'dart:convert'; // +++ ضروري لفك تشفير تفاصيل الحجر الصحي +++


class DashboardScreen extends StatefulWidget {
  final int driverId;
  const DashboardScreen({required this.driverId, super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
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
  
  // السجلات المحجورة دليل استرداد محمي وليست سلة محذوفات.
  void _showQuarantineBottomSheet(BuildContext context) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return FutureBuilder<List<Map<String, dynamic>>>(
          future: LocalDatabase.instance.getQuarantinedSyncs(),
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Padding(
                padding: EdgeInsets.all(20),
                child: Center(child: CircularProgressIndicator()),
              );
            }

            final syncs = snapshot.data ?? [];
            if (syncs.isEmpty) {
              return const Padding(
                padding: EdgeInsets.all(20),
                child: Text('لا توجد عمليات تحتاج معالجة.'),
              );
            }

            return Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.report_problem_outlined,
                    color: Colors.orange,
                    size: 48,
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'عمليات أوفلاين تحتاج معالجة',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'هذه السجلات محفوظة لحماية الفواتير والمخزون. لا يمكن حذفها من تطبيق المندوب لمجرد إخفاء الخطأ.',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  Flexible(
                    child: ListView.builder(
                      shrinkWrap: true,
                      itemCount: syncs.length,
                      itemBuilder: (context, index) {
                        final item = syncs[index];
                        String visitIdInfo = '';
                        String fallbackReason = '';
                        try {
                          final payload = jsonDecode(item['payload']);
                          fallbackReason =
                              payload['quarantine_reason']?.toString() ?? '';
                          visitIdInfo = payload['visitId'] != null
                              ? ' (زيارة #${payload['visitId']})'
                              : '';
                        } catch (_) {}

                        final type = item['type']
                                ?.toString()
                                .replaceFirst('quarantined_', '') ??
                            'unknown';
                        final code =
                            item['last_error_code']?.toString() ?? 'غير مصنف';
                        final reason =
                            item['last_error_message']?.toString().trim();
                        final displayReason =
                            (reason != null && reason.isNotEmpty)
                                ? reason
                                : (fallbackReason.isNotEmpty
                                    ? fallbackReason
                                    : 'تحتاج مراجعة قبل إعادة المحاولة.');

                        return Card(
                          child: ListTile(
                            leading: const Icon(
                              Icons.shield_outlined,
                              color: Colors.orange,
                            ),
                            title: Text(
                              'عملية: $type$visitIdInfo',
                              style:
                                  const TextStyle(fontWeight: FontWeight.bold),
                            ),
                            subtitle: Text(
                              'الرمز: $code\n'
                              'السبب: $displayReason\n'
                              'التاريخ: ${item['created_at']?.toString().split('T').first ?? ''}',
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  // --- دالة بناء المحتوى (تعتمد 100% على الـ State) ---
  Widget _buildDashboardContent(DashboardLoaded state) {
    return RefreshIndicator(
      // +++ الكيّ الجراحي: إشعار المزامنة مع مؤشر التحميل وانتظار البلوك +++
      onRefresh: () async {
        // +++ الكيّ الجراحي: فحص الخزنة أولاً. لا نظهر الإشعار إلا إذا كان هناك فواتير معلقة +++
        // +++  (البند 2): فلترة الجثث (quarantined) حتى لا نخدع المندوب +++
        final allSyncs = await LocalDatabase.instance.getPendingSyncs();
        final pendingSyncs = allSyncs.where((p) => !(p['type']?.toString().startsWith('quarantined_') ?? false)).toList();

        // +++ الحارس الأمني: التأكد أن الشاشة لا تزال مفتوحة بعد فجوة الانتظار (Async Gap) +++
        if (!mounted) return;

        final bool hasPendingData = pendingSyncs.isNotEmpty;

        ScaffoldFeatureController? loadingSnackBar;
        if (hasPendingData) {
          loadingSnackBar = ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Row(
                children: [
                  SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)),
                  SizedBox(width: 15),
                  Text('جاري رفع فواتير الأوفلاين... الرجاء الانتظار', style: TextStyle(fontWeight: FontWeight.bold)),
                ],
              ),
              backgroundColor: Colors.orange,
              duration: Duration(days: 1), 
            ),
          );
        }

        final bloc = context.read<DashboardBloc>();
        bool isTimeout = false;
        StreamSubscription? subscription;
        
        try {
          final completer = Completer<void>();
          subscription = bloc.stream.listen((state) {
            if (state is DashboardError) {
              if (!completer.isCompleted) completer.completeError(state.message);
            } else if (state is! DashboardLoading && state is! DashboardInitial && !completer.isCompleted) {
              completer.complete();
            }
          });
          
          bloc.add(const ForceSyncData());
          await completer.future.timeout(const Duration(seconds: 8));
          
        } on TimeoutException catch (_) {
          isTimeout = true;
          developer.log('[Dashboard] Refresh timeout reached.');
        } catch (e) {
          developer.log('[Dashboard] Refresh error: $e');
          // +++   إغلاق لافتة التحميل حصراً بدون المساس بلافتات الأخطاء القادمة من الـ BLoC +++
          loadingSnackBar?.close();
          await subscription?.cancel();
          return; 
        } finally {
          await subscription?.cancel(); 
        }

        // إغلاق لافتة التحميل بأمان
        loadingSnackBar?.close();

        if (mounted && hasPendingData) {
          // +++  2: التأكد من تفريغ الخزنة فعلياً قبل إعلان النجاح للمندوب +++
          final allRemaining = await LocalDatabase.instance.getPendingSyncs();
          final remainingSyncs = allRemaining.where((p) => !(p['type']?.toString().startsWith('quarantined_') ?? false)).toList();
          
          // +++   درع الـ Context عبر الفجوة الزمنية (Async Gap) لمنع التحذيرات والكراش +++
          if (!mounted) return;
          
          if (isTimeout) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('انتهى وقت المزامنة. قد تكون الشبكة ضعيفة ⚠️'),
                backgroundColor: Colors.orange,
                duration: Duration(seconds: 4),
              ),
            );
          } else if (remainingSyncs.isNotEmpty) {
             ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('تم تحديث البيانات، ولكن فشل رفع بعض الفواتير. يرجى التأكد من الإنترنت ⚠️'),
                backgroundColor: Colors.orange,
                duration: Duration(seconds: 4),
              ),
            );
          } else {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('تم رفع الفواتير وتحديث البيانات بنجاح ✔️'),
                backgroundColor: Colors.green,
                duration: Duration(seconds: 3),
              ),
            );
          }
        }
      },
      child: ListView(
        padding: const EdgeInsets.all(16.0),
        children: [
          // +++   لافتة الحجر الصحي الحمراء (تظهر فقط إذا كان هناك فواتير مرفوضة) +++
          // +++   لافتة الحجر الصحي التفاعلية +++
          if (state.quarantinedVisits > 0)
            InkWell(
              onTap: () => _showQuarantineBottomSheet(context),
              borderRadius: BorderRadius.circular(8),
              child: Container(
                padding: const EdgeInsets.all(12),
                margin: const EdgeInsets.only(bottom: 10),
                decoration: BoxDecoration(
                  color: Colors.red.shade900,
                  borderRadius: BorderRadius.circular(8),
                  boxShadow: const [BoxShadow(color: Colors.redAccent, blurRadius: 5)],
                ),
                child: Row(
                  children: [
                    const Icon(Icons.touch_app, color: Colors.white, size: 30),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'يوجد (${state.quarantinedVisits}) عمليات تحتاج معالجة قبل متابعة المزامنة. اضغط للتفاصيل.',
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
                      ),
                    ),
                  ],
                ),
              ),
            ),

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

          VehicleInventorySection(
            products: state.products,
            nonSellableCustody: state.nonSellableCustody,
          ),
        ],
      ),
    );
  }
}
