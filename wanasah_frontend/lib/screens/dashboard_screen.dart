import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../blocs/dashboard/dashboard_event.dart';
import '../blocs/dashboard/dashboard_state.dart';
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import '../blocs/auth/auth_state.dart'; 
import 'package:intl/intl.dart';
import 'login_screen.dart';
import 'visit_list_screen.dart';
import 'dart:async';
import 'dart:developer' as developer; 
import '../core/db/local_database.dart';

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

// --- دوال إدارة العمل (منقولة للـ BLoC للـ Clean Architecture) ---
  Future<void> _startWork() async {
    context.read<DashboardBloc>().add(StartSessionEvent(driverId: widget.driverId));
  }

  Future<void> _endWork() async {
    context.read<DashboardBloc>().add(EndSessionEvent(driverId: widget.driverId));
  }

  Future<void> _toggleBreak(String action) async {
    context.read<DashboardBloc>().add(ToggleBreakEvent(driverId: widget.driverId, action: action));
  }

  // --- دالة إظهار نافذة الحوالات المعلقة المجمعة (النسخة الديناميكية الفولاذية) ---
  void _showTransferDialog(
    BuildContext context,
    Map<String, dynamic> batchData,
  ) {
    final List<dynamic> items = batchData['items'] ?? [];
    // +++ الكي الجراحي لـ Bug 4: التحقق من أن الأصناف صالحة وليست وهمية قبل الفتح +++
    final int validItemsCount = items.where((item) => (item['real_transfer_id'] as num?)?.toInt() != 0 && item['real_transfer_id'] != null).length;

    if (items.isEmpty || validItemsCount == 0) {
      _isShowingDialog = false;
      return; 
    }

    Map<int, String> itemResponses = {};

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {

        return PopScope(
          canPop: false,
          child: AlertDialog(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            title: const Row(
              children: [
                Icon(Icons.inventory_2_outlined, color: Colors.blue),
                SizedBox(width: 8),
                Text(
                  'تحديث عهدة من الإدارة',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                ),
              ],
            ),
            content: SizedBox(
              width: double.maxFinite,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'قامت الإدارة بإجراء التعديلات التالية على عهدتك. هل توافق؟',
                    style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 10),
                  // +++ قائمة ديناميكية تفصل السحب عن الإضافة لكل صنف +++
                  Flexible(
                    child: ListView.builder(
                      shrinkWrap: true,
                      itemCount: items.length,
                      itemBuilder: (context, index) {
                        final item = items[index];
                        final String productName =
                            item['product_name'] ?? 'غير معروف';

                        // +++ اللوجيك الدقيق لمعرفة السحب من الإضافة +++
                        final int rawCartons = item['delta_cartons'] ?? 0;
                        final int rawPacks = item['delta_packs'] ?? 0;
                        final bool isAddition =
                            rawCartons > 0 || (rawCartons == 0 && rawPacks > 0);

                        final int absCartons = rawCartons.abs();
                        final int absPacks = rawPacks.abs();

                        return Card(
                          color:
                              isAddition
                                  ? Colors.green.shade50
                                  : Colors.red.shade50,
                          elevation: 0,
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          child: ListTile(
                            dense: true,
                            leading: Icon(
                              isAddition
                                  ? Icons.add_circle
                                  : Icons.remove_circle,
                              color: isAddition ? Colors.green : Colors.red,
                            ),
                            title: Text(
                              productName,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            subtitle: Text(
                              isAddition ? 'إضافة للسيارة' : 'سحب من السيارة',
                              style: TextStyle(
                                color:
                                    isAddition
                                        ? Colors.green[700]
                                        : Colors.red[700],
                                fontWeight: FontWeight.bold,
                                fontSize: 12,
                              ),
                            ),
                            trailing: StatefulBuilder(
                              builder: (context, setState) {
                                // +++ الكي الجراحي 8: التحويل الآمن لمنع الـ TypeError Crash +++
                                final itemId = (item['real_transfer_id'] as num?)?.toInt() ?? 0;
                                if (itemId == 0) return const SizedBox.shrink();
                                final currentResponse = itemResponses[itemId];

                                // +++ النسف المعماري (بسيط 2): ضبط الأبعاد وإغلاق الأقواس بشكل سليم 100% +++
                                return ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 150,
                                  ),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    mainAxisAlignment: MainAxisAlignment.end,
                                    children: [
                                      Expanded(
                                        child: Text(
                                          '$absCartons كرتونة\n$absPacks حبة',
                                          textAlign: TextAlign.center,
                                          softWrap: false,
                                          overflow: TextOverflow.visible,
                                          style: const TextStyle(
                                            fontSize: 12,
                                            fontWeight: FontWeight.bold,
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 4),
                                      // +++ الدرع الديمقراطي: أزرار الرفض والقبول لكل صنف +++
                                      IconButton(
                                        padding: EdgeInsets.zero,
                                        constraints: const BoxConstraints(),
                                        icon: Icon(
                                          Icons.close,
                                          color:
                                              currentResponse == 'rejected'
                                                  ? Colors.red
                                                  : Colors.grey,
                                        ),
                                        onPressed:
                                            () => setState(
                                              () =>
                                                  itemResponses[itemId] =
                                                      'rejected',
                                            ),
                                      ),
                                      const SizedBox(width: 4),
                                      IconButton(
                                        padding: EdgeInsets.zero,
                                        constraints: const BoxConstraints(),
                                        icon: Icon(
                                          Icons.check,
                                          color:
                                              currentResponse == 'accepted'
                                                  ? Colors.green
                                                  : Colors.grey,
                                        ),
                                        onPressed:
                                            () => setState(
                                              () =>
                                                  itemResponses[itemId] =
                                                      'accepted',
                                            ),
                                      ),
                                    ],
                                  ),
                                );
                              },
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.blue),
                onPressed: () {
                  // التأكد من أن المندوب أجاب على كل الأصناف السليمة فقط
                  final int validItemsCount = items.where((item) => (item['real_transfer_id'] as num?)?.toInt() != 0 && item['real_transfer_id'] != null).length;
                  if (itemResponses.length != validItemsCount) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text(
                          'يجب الرد على جميع الأصناف بالقبول أو الرفض',
                        ),
                        backgroundColor: Colors.red,
                      ),
                    );
                    return;
                  }

                  // +++ الدرع الفولاذي ضد النقر المزدوج (True Lock Mechanism) +++
                  if (!_isShowingDialog) return; // إذا تم الضغط مسبقاً، اقتل النقرة الثانية فوراً
                  _isShowingDialog = false; // أقفل الباب وراءك
                  
                  final dashboardBloc = context.read<DashboardBloc>();
                  Navigator.pop(dialogContext);

                  // +++ إرسال المصفوفة التفصيلية للسيرفر +++
                  final List<Map<String, dynamic>> detailedResponses =
                      itemResponses.entries
                          .map((e) => {'transfer_id': e.key, 'status': e.value})
                          .toList();

                  // +++ سيتم تعديل الـ Event لاحقاً ليقبل هذه المصفوفة +++
                  dashboardBloc.add(
                    RespondToBatchTransfer(
                      transferIds: [],
                      responseStatus: 'mixed',
                      detailedTransfers: detailedResponses,
                    ),
                  );
                },
                child: const Text(
                  'إرسال الرد',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
              ),
            ],
          ),
        );
      },
    ).then((_) {
      // +++ الكي الجراحي: تحرير القفل عند إغلاق النافذة بأي طريقة (زر أو غيره) لضمان ظهور النوافذ القادمة +++
      if (mounted) {
        _isShowingDialog = false;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // +++ النسف المعماري لظاهرة الأشباح: لون صلب يمنع الشفافية +++
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
              bool isActive = state is DashboardLoaded && state.isActiveSession;
              return IconButton(
                icon: const Icon(Icons.logout),
                tooltip: 'تسجيل الخروج',
                onPressed: isActive ? null : _logout,
              );
            },
          ),
        ],
      ),
      // +++ هنا يتجلى ذكاء الـ MultiBlocListener لربط التطبيق ككتلة واحدة +++
      body: MultiBlocListener(
        listeners: [
          // +++ الكيّ الجراحي 2: سد ثغرة (الزومبي). الاستماع للـ AuthBloc لطرد المستخدم فوراً إذا انتهت الجلسة (401) أو قام بتسجيل الخروج +++
          BlocListener<AuthBloc, AuthState>(
            listener: (context, state) {
              if (state is AuthUnauthenticated) {
                Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const LoginScreen()),
                  (Route<dynamic> route) => false,
                );
              }
            },
          ),
          BlocListener<DashboardBloc, DashboardState>(
            listener: (context, state) {
              // +++ الكي الجراحي لـ Bug 1: تحرير الزر فور انتهاء أي عملية (نجاح، فشل، أو تحميل داتا) +++
              if (state is! DashboardLoading && state is! DashboardInitial) {
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
                // +++ الكي الجراحي: اصطياد رسائل النجاح المدمجة بالـ State بدون تدمير الشجرة +++
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

  // --- دالة بناء المحتوى (تعتمد 100% على الـ State) ---
  Widget _buildDashboardContent(DashboardLoaded state) {
    String startTimeFormatted = '';
    if (state.isActiveSession && state.activeSessionStartTime != null) {
      try {
        final startTime =
            DateTime.parse(state.activeSessionStartTime!).toLocal();
        startTimeFormatted = DateFormat('hh:mm a', 'ar').format(startTime);
      } catch (_) {
        startTimeFormatted = "غير معروف";
      }
    }

    return RefreshIndicator(
      // +++ الكيّ الجراحي: إشعار المزامنة مع مؤشر التحميل وانتظار البلوك +++
      onRefresh: () async {
        // +++ الكيّ الجراحي: فحص الخزنة أولاً. لا نظهر الإشعار إلا إذا كان هناك فواتير معلقة +++
        final pendingSyncs = await LocalDatabase.instance.getPendingSyncs();

        // +++ الحارس الأمني: التأكد أن الشاشة لا تزال مفتوحة بعد فجوة الانتظار (Async Gap) +++
        if (!mounted) return;

        final bool hasPendingData = pendingSyncs.isNotEmpty;

        if (hasPendingData) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Row(
                children: [
                  SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      color: Colors.white,
                      strokeWidth: 2,
                    ),
                  ),
                  SizedBox(width: 15),
                  Text(
                    'جاري رفع فواتير الأوفلاين... الرجاء الانتظار',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                ],
              ),
              backgroundColor: Colors.orange,
              duration: Duration(days: 1), // يظل ظاهراً حتى نلغيه برمجياً
            ),
          );
        }

        final bloc = context.read<DashboardBloc>();
        bool isTimeout = false;
        StreamSubscription? subscription;
        
        try {
          // +++ الكي الجراحي 6: تشغيل الـ Listener قبل إرسال الـ Event لمنع الـ False Timeout +++
          final completer = Completer<void>();
          subscription = bloc.stream.listen((state) {
            if (state is DashboardError) {
              if (!completer.isCompleted) completer.completeError(state.message);
            } else if (state is! DashboardLoading && state is! DashboardInitial && !completer.isCompleted) {
              completer.complete();
            }
          });
          
          // +++ الكي الجراحي 4: احترام معمارية BLoC بطلب المزامنة القسرية كحدث، بدلاً من تجاوز البلوك +++
          bloc.add(const ForceSyncData());
          // FetchDashboardData يتم طلبه من داخل ForceSyncData في البلوك، لا نحتاج طلبه هنا مجدداً.
          
          await completer.future.timeout(const Duration(seconds: 8));
          
        } on TimeoutException catch (_) {
          isTimeout = true;
          developer.log('[Dashboard] Refresh timeout reached.');
        } catch (e) {
          developer.log('[Dashboard] Refresh error: $e');
          // +++ الكي الجراحي لـ Bug 2: نكتفي بإخفاء إشعار التحميل والإجهاض، ونترك הـ BlocListener يعرض الخطأ الأحمر +++
          if (mounted) {
            ScaffoldMessenger.of(context).hideCurrentSnackBar();
          }
          await subscription?.cancel();
          return; // إجهاض العملية هنا فوراً
        } finally {
          await subscription?.cancel(); 
        }

        // إخفاء إشعار التحميل فقط في حالات النجاح أو הـ Timeout
        if (mounted) {
          ScaffoldMessenger.of(context).hideCurrentSnackBar();
        }

        if (mounted && hasPendingData) {
          // +++ الكي الجراحي 2: التأكد من تفريغ الخزنة فعلياً قبل إعلان النجاح للمندوب +++
          final remainingSyncs = await LocalDatabase.instance.getPendingSyncs();
          
          // +++ الكي الجراحي: درع الـ Context عبر الفجوة الزمنية (Async Gap) لمنع التحذيرات والكراش +++
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

          Center(
            child: Text(
              state.isActiveSession
                  ? 'جاري العمـل (بدأ الساعة: $startTimeFormatted)'
                  : 'اضغط لبدء العمل',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color:
                    state.isActiveSession ? Colors.green[700] : Colors.red[700],
              ),
            ),
          ),
          const SizedBox(height: 15),
          Center(
            child: ElevatedButton.icon(
              icon: Icon(
                state.isActiveSession
                    ? Icons.stop_circle_outlined
                    : Icons.play_arrow,
              ),
              label: Text(state.isActiveSession ? 'إنهاء العمل' : 'بدء العمل'),
              onPressed: (_isActionInProgress || state is DashboardLoading) ? null : () async {
                if (state.isActiveSession && state.isOnBreak) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('يجب إنهاء الاستراحة أولاً!'),
                      backgroundColor: Colors.orange,
                    ),
                  );
                  return;
                }
                
                final bool? confirmed = await _showConfirmationDialog(
                  context,
                  state.isActiveSession ? 'إنهاء العمل؟' : 'بدء العمل؟',
                  state.isActiveSession ? 'هل تريد إنهاء جلسة العمل الحالية؟' : 'هل تريد بدء جلسة عمل جديدة؟',
                );
                
                // +++ الكي الجراحي لـ Bug 1: حماية הـ setState من الـ Unmounted Crash +++
                if (!mounted) return;

                if (confirmed == true) {
                  // +++ إقفال الزر ولا نفتحه إلا من خلال הـ BlocListener لمنع التكرار +++
                  setState(() => _isActionInProgress = true);
                  if (state.isActiveSession) {
                    _endWork();
                  } else {
                    _startWork();
                  }
                }
              },
              style: ElevatedButton.styleFrom(
                backgroundColor:
                    state.isActiveSession ? Colors.red[600] : Colors.green[600],
                padding: const EdgeInsets.symmetric(
                  horizontal: 30,
                  vertical: 12,
                ),
                textStyle: const TextStyle(fontSize: 16),
              ),
            ),
          ),

          if (state.isActiveSession) ...[
            const SizedBox(height: 10),
            Center(
              child: ElevatedButton.icon(
                onPressed: (_isActionInProgress || state is DashboardLoading) ? null : () {
                  // +++ إقفال الزر ولا نفتحه إلا من خلال הـ BlocListener +++
                  setState(() => _isActionInProgress = true);
                  _toggleBreak(state.isOnBreak ? 'end' : 'start');
                },
                icon: Icon(
                  state.isOnBreak
                      ? Icons.free_breakfast_outlined
                      : Icons.free_breakfast,
                ),
                label: Text(
                  state.isOnBreak ? 'إنهاء الاستراحة' : 'بدء الاستراحة',
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor:
                      state.isOnBreak ? Colors.orange[700] : Colors.blue[600],
                  padding: const EdgeInsets.symmetric(
                    horizontal: 30,
                    vertical: 12,
                  ),
                  textStyle: const TextStyle(fontSize: 16),
                ),
              ),
            ),
          ],

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

          const SizedBox(height: 20),
          const Divider(height: 30, thickness: 1),
          Text(
            'مخزون سيارة المندوب:',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),

          if (state.products.isEmpty)
            Container(
              padding: const EdgeInsets.all(16.0),
              decoration: BoxDecoration(
                color: Colors.red[50],
                borderRadius: BorderRadius.circular(8.0),
                border: Border.all(color: Colors.red.shade200),
              ),
              child: const Center(
                child: Text(
                  'لا يوجد بضاعة في السيارة حالياً.',
                  style: TextStyle(
                    fontSize: 16,
                    color: Colors.red,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),

          if (state.products.isNotEmpty)
            ...state.products.map((item) {
              return Padding(
                padding: const EdgeInsets.only(bottom: 12.0),
                child: Container(
                  padding: const EdgeInsets.all(12.0),
                  decoration: BoxDecoration(
                    color: Colors.grey[100],
                    borderRadius: BorderRadius.circular(8.0),
                    border: Border.all(color: Colors.grey.shade300),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.name,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          // +++ الاعتماد الكلي على السيرفر (Single Source of Truth) لنسف الطعريس +++
                          Text(
                            'الاستلام: ${item.startingCartons} كرتونة${item.startingPacks > 0 ? ' و ${item.startingPacks} حبة' : ''}',
                            style: const TextStyle(fontSize: 14),
                          ),
                          Text(
                            'المباع: ${item.soldCartons} كرتونة، ${item.soldPacks} حبة',
                            style: TextStyle(
                              fontSize: 14,
                              color: Colors.green[700],
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'المتبقي: ${item.currentCartons} كرتونة، ${item.currentPacks} باكيت',
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.bold,
                          color: Colors.blueAccent,
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }),
          const SizedBox(height: 20),
        ],
      ),
    );
  }
}
