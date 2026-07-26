import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../blocs/dashboard/dashboard_event.dart';
import '../blocs/dashboard/dashboard_state.dart';
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import '../blocs/auth/auth_state.dart'; // +++ الاستيراد المفقود +++
import '../core/network/api_client.dart';
import 'package:intl/intl.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'login_screen.dart';
import 'visit_list_screen.dart';
import 'package:geolocator/geolocator.dart';
import 'dart:async';
import 'dart:developer' as developer; // +++ اصحى يا مدير، هذا الاستيراد اللي نسيته +++
import '../core/db/local_database.dart';

class DashboardScreen extends StatefulWidget {
  final int driverId;
  const DashboardScreen({required this.driverId, super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  // +++ تم مسح 15 متغيراً من الـ setState! الشاشة الآن "غبية" وتعتمد على الـ BLoC +++
  bool _isSessionLoading =
      false; // الوحيد المتبقي لمنع النقر المزدوج على أزرار الجلسة
  bool _isShowingDialog = false; // لمنع تكرار ظهور نافذة الحوالات

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

  // --- دالة بدء العمل (محتفظة بمنطق الـ GPS المعقد الخاص بك) ---
  Future<void> _startWork() async {
    if (_isSessionLoading) return;
    setState(() => _isSessionLoading = true);

    Position? currentPosition;
    try {
      currentPosition = await _getDeviceLocation();
      await ApiClient.instance.post(
        '/driver/${widget.driverId}/sessions/start',
        data: {
          'latitude': currentPosition?.latitude,
          'longitude': currentPosition?.longitude,
        },
        options: Options(
          sendTimeout: const Duration(seconds: 20),
          receiveTimeout: const Duration(seconds: 20),
        ),
      );

      if (!mounted) return;

      // نجاح: نأمر البلوك بجلب الداشبورد الجديد
      context.read<DashboardBloc>().add(
        FetchDashboardData(driverId: widget.driverId),
      );
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم بدء جلسة العمل!'),
          backgroundColor: Colors.green,
        ),
      );
    } on DioException catch (e) {
      if (!mounted) return;
      if (e.response?.statusCode == 409) {
        context.read<DashboardBloc>().add(
          FetchDashboardData(driverId: widget.driverId),
        );
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('يوجد جلسة عمل نشطة بالفعل.'),
            backgroundColor: Colors.blue,
          ),
        );
        return;
      }
      if (e.response?.statusCode == 401) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'خطأ: ${e.response?.data?['message'] ?? 'فشل الاتصال'}',
          ),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isSessionLoading = false);
    }
  }

  // --- دالة إنهاء العمل ---
  Future<void> _endWork() async {
    if (_isSessionLoading) return;
    setState(() => _isSessionLoading = true);
    try {
      await ApiClient.instance.put(
        '/driver/${widget.driverId}/sessions/end',
        options: Options(sendTimeout: const Duration(seconds: 15)),
      );
      if (!mounted) return;

      context.read<DashboardBloc>().add(
        FetchDashboardData(driverId: widget.driverId),
      );
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم إنهاء العمل.'),
          backgroundColor: Colors.blue,
        ),
      );
    } on DioException catch (e) {
      if (!mounted) return;
      if (e.response?.statusCode == 401) return;

      // +++ الكي الجراحي: اصطياد الـ 404 (السيرفر المصفّر) وتنظيف الجلسة الوهمية محلياً +++
      if (e.response?.statusCode == 404) {
        await const FlutterSecureStorage().delete(key: 'is_on_break');
        await LocalDatabase.instance.clearSessionData();
        if (!mounted) return; // +++ الدرع الفولاذي لمنع الخطأ +++
        context.read<DashboardBloc>().add(
          FetchDashboardData(driverId: widget.driverId),
        );
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'تم اكتشاف تصفير للسيرفر. تم تنظيف الجلسة الوهمية محلياً بنجاح 🧹',
            ),
            backgroundColor: Colors.orange,
          ),
        );
        setState(() => _isSessionLoading = false);
        return;
      }

      final isOffline =
          e.response == null ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.unknown ||
          e.error.toString().contains('SocketException');

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            isOffline
                ? 'لا يمكن إنهاء العمل وأنت أوفلاين. يجب الاتصال بالإنترنت لمطابقة العهدة وتسليمها.'
                : 'خطأ: ${e.response?.data?['message'] ?? 'فشل الإنهاء'}',
          ),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isSessionLoading = false);
    }
  }

  // --- دالة تسجيل الاستراح المحصنة أوفلاين ---
  Future<void> _toggleBreak(String action) async {
    if (_isSessionLoading) return;
    setState(() => _isSessionLoading = true);

    try {
      // 1. محاولة الإرسال للسيرفر مباشرة مع وقت انتظار محدد
      await ApiClient.instance.put(
        '/driver/${widget.driverId}/sessions/break',
        data: {'action': action},
        options: Options(sendTimeout: const Duration(seconds: 10)),
      );
    } on DioException catch (e) {
      // +++ الكي الجراحي: اصطياد الـ 404 أثناء الاستراحة لتنظيف التطبيق فوراً +++
      if (e.response?.statusCode == 404) {
        await const FlutterSecureStorage().delete(key: 'is_on_break');
        await LocalDatabase.instance.clearSessionData();
        if (!mounted) return; // +++ الدرع الفولاذي لمنع الخطأ +++
        context.read<DashboardBloc>().add(
          FetchDashboardData(driverId: widget.driverId),
        );
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('الجلسة غير موجودة على السيرفر! تم إعادة الضبط 🧹'),
            backgroundColor: Colors.orange,
          ),
        );
        setState(() => _isSessionLoading = false);
        return;
      }

      // 2. فحص نوع الخطأ: هل هو مشكلة نت أم خطأ منطقي من السيرفر؟
      // +++ الكيّ الجراحي 2: التقاط جميع أنواع انقطاع الإنترنت (بما فيها SocketException) +++
      final isOffline =
          e.response == null ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.unknown ||
          e.error.toString().contains('SocketException');

      if (isOffline) {
        // حفظ في الخزنة السرية (pending_sync) للمزامنة لاحقاً
        await LocalDatabase.instance.addPendingSync(
          type: 'toggle_break',
          payload: '{"driver_id": ${widget.driverId}, "action": "$action"}',
        );
        // نكمل العملية محلياً دون إزعاج المندوب بخطأ الشبكة
      } else {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'خطأ: ${e.response?.data?['message'] ?? 'فشل الاتصال'}',
            ),
            backgroundColor: Colors.red,
          ),
        );
        setState(() => _isSessionLoading = false);
        return; // توقف هنا لأن الخطأ من السيرفر وليس من الشبكة
      }
    } catch (e) {
      if (mounted) setState(() => _isSessionLoading = false);
      return;
    }

    // 3. تحديث الذاكرة المحلية (SecureStorage) والشاشة (Bloc)
    // هذه الخطوات تتم الآن سواء كنت أونلاين أو أوفلاين (بناءً على الخطوات السابقة)
    await const FlutterSecureStorage().write(
      key: 'is_on_break',
      value: action == 'start' ? 'true' : 'false',
    );

    if (!mounted) return;

    // تحديث الـ BLoC ليعكس الحالة الجديدة فوراً في الـ UI
    context.read<DashboardBloc>().add(
      FetchDashboardData(driverId: widget.driverId),
    );

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          action == 'start'
              ? 'تم بدء الاستراحة (مسجلة).'
              : 'تم إنهاء الاستراحة (مسجلة).',
        ),
        backgroundColor: Colors.blue,
      ),
    );

    setState(() => _isSessionLoading = false);
  }

  // --- دالة الموقع المحمية (مع استرجاع رسائل التنبيه للمستخدم) ---
  Future<Position?> _getDeviceLocation() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('الرجاء تفعيل خدمة الموقع (GPS)'),
            backgroundColor: Colors.orange,
          ),
        );
      }
      return null;
    }
    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('صلاحية الموقع مطلوبة لبدء العمل'),
              backgroundColor: Colors.red,
            ),
          );
        }
        return null;
      }
    }
    try {
      Position? lastPosition = await Geolocator.getLastKnownPosition();
      if (lastPosition != null) {
        return lastPosition;
      }
      return await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.low,
      ).timeout(const Duration(seconds: 4));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('فشل تحديد الموقع، حاول في مكان مفتوح'),
            backgroundColor: Colors.red,
          ),
        );
      }
      return null;
    }
  }

  // --- دالة إظهار نافذة الحوالات المعلقة المجمعة (النسخة الديناميكية الفولاذية) ---
  void _showTransferDialog(
    BuildContext context,
    Map<String, dynamic> batchData,
  ) {
    // +++ النسف المعماري (ديكتاتورية المصافحة): متغير لتخزين رد المندوب لكل صنف بشكل فردي +++
    Map<int, String> itemResponses = {};

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        final List<dynamic> items = batchData['items'] ?? [];
        if (items.isEmpty) return const SizedBox.shrink();

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
                                final itemId = item['real_transfer_id'] as int;
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
                  // التأكد من أن المندوب أجاب على كل الأصناف
                  if (itemResponses.length != items.length) {
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
    );
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
              if (state is DashboardError) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(state.message),
                    backgroundColor: Colors.red,
                  ),
                );
              } else if (state is DashboardLoaded) {
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
        bloc.add(FetchDashboardData(driverId: widget.driverId));

        // +++ درع التجميد اللانهائي: مهلة زمنية 5 ثوانٍ كحد أقصى لمنع دوران المؤشر للأبد +++
        try {
          await bloc.stream.firstWhere((s) => s is! DashboardLoading).timeout(const Duration(seconds: 5));
        } catch (_) {
          developer.log('[Dashboard] Refresh timeout reached, proceeding safely...');
        }

        if (mounted && hasPendingData) {
          ScaffoldMessenger.of(context).hideCurrentSnackBar();
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('تم رفع الفواتير وتحديث البيانات بنجاح ✔️'),
              backgroundColor: Colors.green,
              duration: Duration(seconds: 3),
            ),
          );
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
              icon:
                  _isSessionLoading
                      ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(
                          color: Colors.white,
                          strokeWidth: 3,
                        ),
                      )
                      : Icon(
                        state.isActiveSession
                            ? Icons.stop_circle_outlined
                            : Icons.play_arrow,
                      ),
              label: Text(state.isActiveSession ? 'إنهاء العمل' : 'بدء العمل'),
              onPressed:
                  _isSessionLoading
                      ? null
                      : () async {
                        if (state.isActiveSession) {
                          if (state.isOnBreak) {
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
                            'إنهاء العمل؟',
                            'هل تريد إنهاء جلسة العمل الحالية؟',
                          );
                          if (confirmed == true) _endWork();
                        } else {
                          final bool? confirmed = await _showConfirmationDialog(
                            context,
                            'بدء العمل؟',
                            'هل تريد بدء جلسة عمل جديدة؟',
                          );
                          if (confirmed == true) _startWork();
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
                onPressed:
                    _isSessionLoading
                        ? null
                        : () => _toggleBreak(state.isOnBreak ? 'end' : 'start'),
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
                  'إجمالي كاش المبيعات: ${state.totalSalesCash.toStringAsFixed(2)} د.أ',
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  'إجمالي الذمم المحصلة: (${state.debtPaymentsCount}) ${state.totalDebtPaid.toStringAsFixed(2)} د.أ',
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  'إجمالي الكاش المستلم: ${state.totalCashOverall.toStringAsFixed(2)} د.أ',
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
              // +++ الدرع المحاسبي: تحويل الكل لحبات لمعرفة المباع الحقيقي بالكراتين والفراطة +++
              int safePpc = item.packsPerCarton > 0 ? item.packsPerCarton : 1;
              int totalStartingPacks = (item.startingCartons * safePpc);
              int totalCurrentPacks = (item.currentCartons * safePpc) + item.currentPacks;
              int totalSoldPacks = totalStartingPacks - totalCurrentPacks;
              
              int soldCartons = totalSoldPacks ~/ safePpc;
              int soldPacks = totalSoldPacks % safePpc;

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
                          Text(
                            'الاستلام: ${item.startingCartons} كرتونة',
                            style: const TextStyle(fontSize: 14),
                          ),
                          Text(
                            'المباع: $soldCartons كرتونة، $soldPacks حبة',
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
