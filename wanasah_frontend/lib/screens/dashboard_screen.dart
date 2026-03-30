import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../blocs/dashboard/dashboard_event.dart';
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import '../core/network/api_client.dart';
import 'dart:developer' as developer;
import 'package:intl/intl.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'login_screen.dart';
import 'visit_list_screen.dart';
import 'package:geolocator/geolocator.dart';
import 'dart:async';

class DashboardScreen extends StatefulWidget {
  final int driverId;
  const DashboardScreen({required this.driverId, super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  // --- متغيرات الحالة ---
  bool _isLoading = true;
  String? _errorMessage;
  String _driverName = '...';
  String _assignedRegion = '...';
  Map<String, int> _counts = {
    'total_pending': 0,
    'total_completed': 0,
    'sales_in_completed': 0,
  };
  double? _totalSalesCash;
  double? _totalDebtPaid;
  int? _debtPaymentsCount;
  double? _totalCashOverall;
  List<dynamic> _inventoryList = [];
  // ignore: prefer_final_fields
  bool _isActiveSession = false;
  String? _activeSessionStartTime;
  bool _isSessionLoading = false; // لتحميل أزرار البدء/الإنهاء
  // +++ متغيرات الاستراحة والصلاحية +++
  bool _isOnBreak = false;
  // +++++++++++++++++++++++++++++++++

  // --- دالة مساعدة لعرض مربع حوار التأكيد ---
  Future<bool?> _showConfirmationDialog(
    BuildContext context,
    String title,
    String content,
  ) async {
    // استخدام showDialog لعرض مربع حوار، ونوعه bool لأنه سيعيد true أو false
    return await showDialog<bool>(
      context: context,
      barrierDismissible: false, // يجب على المستخدم الضغط على زر للخروج
      builder: (BuildContext dialogContext) {
        // dialogContext هو context الخاص بمربع الحوار
        return AlertDialog(
          title: Text(title), // عنوان مربع الحوار
          content: Text(content), // محتوى الرسالة
          actions: <Widget>[
            TextButton(
              child: const Text('إلغاء'), // زر الإلغاء
              onPressed: () {
                // عند الضغط على إلغاء، أغلق مربع الحوار وأعد القيمة false
                Navigator.of(dialogContext).pop(false);
              },
            ),
            TextButton(
              child: const Text('نعم، تأكيد'), // زر التأكيد
              onPressed: () {
                // عند الضغط على تأكيد، أغلق مربع الحوار وأعد القيمة true
                Navigator.of(dialogContext).pop(true);
              },
            ),
          ],
        );
      },
    );
  }
  // --- نهاية الدالة المساعدة ---

  // --- دالة تسجيل الخروج ---
  Future<void> _logout() async {
    // يفضل عرض تأكيد قبل الخروج أيضاً (اختياري لكن جيد)
    final bool? confirmed = await _showConfirmationDialog(
      // استخدام نفس دالة التأكيد
      context,
      'تأكيد تسجيل الخروج',
      'هل أنت متأكد أنك تريد تسجيل الخروج؟',
    );

    if (confirmed == true) {
      developer.log('User confirmed logout. Clearing stored credentials...');
      const storage = FlutterSecureStorage();

      try {
        // مسح التوكن ومعرف السائق
        await storage.delete(key: 'auth_token');
        await storage.delete(key: 'driver_id');
        developer.log('Credentials cleared.');

        // التأكد أن الويدجت لا يزال موجوداً قبل الانتقال
        if (!mounted) return;

        context.read<AuthBloc>().add(const LogoutEvent());

        // +++ الحل الجذري: إجبار الواجهة على الانتقال لشاشة الدخول فوراً وقتل الزومبي +++
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
          (Route<dynamic> route) => false,
        );
      } catch (e) {
        developer.log('Error during logout: $e');
        // عرض رسالة خطأ إذا فشل المسح أو الانتقال
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('حدث خطأ أثناء تسجيل الخروج.'),
              backgroundColor: Colors.red,
            ),
          );
        }
      }
    } else {
      developer.log('User cancelled logout.');
    }
  }
  // --- نهاية دالة تسجيل الخروج ---

  @override
  void initState() {
    super.initState();
    _fetchDashboardData();
  }

  // --- دالة جلب بيانات الـ Dashboard (نسخة معمارية متقدمة) ---
  Future<void> _fetchDashboardData() async {
    if (!mounted) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    String? errorMsgForState;

    try {
      // +++ استخدام ApiClient الذي يعالج التوكن وخطأ 401 تلقائياً +++
      final response = await ApiClient.instance.get(
        '/driver/${widget.driverId}/dashboard',
      );

      if (!mounted) return;

      // البيانات تأتي مفكوكة التشفير (Map) جاهزة من Dio
      final Map<String, dynamic> data = response.data;

      // استخلاص بيانات الجلسة النشطة
      final Map<String, dynamic>? sessionData =
          data['active_session'] as Map<String, dynamic>?;
      bool sessionIsActive =
          (sessionData != null && sessionData['session_id'] != null);

      bool isAuthorized = false;
      bool isOnBreak = false;
      if (sessionData != null) {
        isAuthorized = sessionData['is_authorized_to_sell'] == true;
        isOnBreak =
            sessionData['break_start_time'] != null &&
            sessionData['break_end_time'] == null;
      }

      const storage = FlutterSecureStorage();
      await storage.write(key: 'is_authorized', value: isAuthorized.toString());

      // استخلاص باقي البيانات
      final Map<String, dynamic>? financials =
          data['financials'] as Map<String, dynamic>?;
      final double totalSalesCash =
          (financials?['total_sales_cash'] as num?)?.toDouble() ?? 0.0;
      final double totalDebtPaid =
          (financials?['total_debt_paid'] as num?)?.toDouble() ?? 0.0;
      final int debtPaymentsCount =
          financials?['debt_payments_count'] as int? ?? 0;
      final double totalCashOverall =
          (financials?['total_cash_overall'] as num?)?.toDouble() ?? 0.0;

      String? startTimeStr;
      List<dynamic> inventoryList = [];
      if (sessionData != null) {
        startTimeStr = sessionData['start_time'] as String?;
        inventoryList = sessionData['inventory'] as List<dynamic>? ?? [];
      }

      final Map<String, dynamic>? countsData =
          data['counts'] as Map<String, dynamic>?;
      final Map<String, int> counts = {
        'total_pending': countsData?['total_pending'] as int? ?? 0,
        'total_completed': countsData?['total_completed'] as int? ?? 0,
        'sales_in_completed': countsData?['sales_in_completed'] as int? ?? 0,
      };

      setState(() {
        _driverName = data['driver_name'] as String? ?? 'غير متوفر';
        _assignedRegion = data['assigned_region'] as String? ?? 'غير محددة';
        _counts = counts;
        _totalSalesCash = totalSalesCash;
        _totalDebtPaid = totalDebtPaid;
        _debtPaymentsCount = debtPaymentsCount;
        _totalCashOverall = totalCashOverall;
        _isActiveSession = sessionIsActive;
        _activeSessionStartTime = startTimeStr;
        _inventoryList = inventoryList;
        _isOnBreak = isOnBreak;
        _isLoading = false;
        _errorMessage = null;
      });

      // +++ إعطاء أمر للعقل المدبر لمزامنة وجلب الزيارات لقاعدة البيانات المحلية +++
      if (mounted) {
        context.read<DashboardBloc>().add(const ForceSyncData());
      }
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        return; // +++ صمت استراتيجي: الانترسبتور سيقوم بالطرد ولا داعي لرسالة الخطأ الحمراء +++
      }

      developer.log(
        'Dashboard Network EXCEPTION: ${e.message}',
        name: 'DashboardFetch',
      );
      if (!mounted) return;
      errorMsgForState = 'فشل الاتصال بالخادم: ${e.message}';
    } catch (error, stacktrace) {
      // +++ إرجاع الطباعة لأسلوب الإنتاج لتنظيف التحذيرات +++
      developer.log(
        '================ كسر معمارية البيانات ================',
        name: 'DashboardFetch',
      );
      developer.log(
        'Error Type: $error',
        name: 'DashboardFetch',
        error: error,
        stackTrace: stacktrace,
      );
      developer.log(
        '======================================================',
        name: 'DashboardFetch',
      );

      if (!mounted) return;
      // عرض الخطأ التقني الفعلي للمطور على الشاشة مباشرة
      errorMsgForState = 'خطأ المعالجة: $error';
    } finally {
      if (mounted && (_isLoading || errorMsgForState != null)) {
        setState(() {
          _isLoading = false;
          if (errorMsgForState != null) {
            _errorMessage = errorMsgForState;
          }
        });
      }
      if (errorMsgForState == null && _isActiveSession) {
        _checkPendingTransfers();
      }
    }
  }
  // --- نهاية دالة جلب بيانات الـ Dashboard ---

  // --- دالة بدء العمل (معدلة لتشمل جلب الموقع وإرساله معمارياً) ---
  Future<void> _startWork() async {
    if (_isSessionLoading) return;
    setState(() => _isSessionLoading = true);

    developer.log(
      "Start Work button pressed. Attempting to get location first...",
    );
    Position? currentPosition;
    String? errorMsg;

    try {
      currentPosition = await _getDeviceLocation();

      if (currentPosition == null) {
        developer.log(
          "Failed to get location, but proceeding without it to prevent blocking work.",
        );
      } else {
        developer.log(
          "Location obtained: Lat: ${currentPosition.latitude}, Lng: ${currentPosition.longitude}.",
        );
      }

      // إرسال الطلب مع مهلة مخصصة 20 ثانية كما طلبت
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

      // 201: جلسة جديدة (نجاح)
      developer.log("Session started. Fetching dashboard data...");
      await _fetchDashboardData();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('تم بدء جلسة العمل بنجاح!'),
            backgroundColor: Colors.green,
          ),
        );
      }
    } on DioException catch (e) {
      if (!mounted) return;

      // 409: جلسة موجودة مسبقاً (نجاح جزئي، Dio يعتبرها Exception لأنها ليست 2xx)
      if (e.response?.statusCode == 409) {
        developer.log("Session already active. Fetching dashboard data...");
        await _fetchDashboardData();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('يوجد جلسة عمل نشطة بالفعل لهذا اليوم.'),
              backgroundColor: Colors.blue,
            ),
          );
        }
        return;
      }

      if (e.response?.statusCode == 401) return; // الانترسبتور يتولى الأمر

      // معالجة خطأ المهلة (Timeout) في شبكة Dio
      if (e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.sendTimeout) {
        errorMsg = 'انتهت مهلة الاتصال بالخادم (20 ثانية).';
      } else {
        errorMsg =
            e.response?.data?['message'] ??
            'فشل بدء جلسة العمل (${e.response?.statusCode})';
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('خطأ: $errorMsg'), backgroundColor: Colors.red),
      );
    } catch (e, s) {
      developer.log(
        'Error during start work process: $e',
        error: e,
        stackTrace: s,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('حدث خطأ: ${e.toString()}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSessionLoading = false);
      developer.log("Finished start work attempt.");
    }
  }

  // --- دالة إنهاء العمل (معدلة لمعمارية ApiClient مع الحفاظ على المهلة والسجلات) ---
  Future<void> _endWork() async {
    if (_isSessionLoading) return;
    setState(() {
      _isSessionLoading = true;
      _errorMessage = null;
    });

    developer.log('Ending work session for driver: ${widget.driverId}');
    try {
      final response = await ApiClient.instance.put(
        '/driver/${widget.driverId}/sessions/end',
        options: Options(
          sendTimeout: const Duration(seconds: 15),
          receiveTimeout: const Duration(seconds: 15),
        ),
      );

      if (!mounted) return;

      developer.log('End session response: ${response.data}');
      setState(() {
        _isActiveSession = false;
        _isSessionLoading = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم إنهاء جلسة العمل بنجاح.'),
          backgroundColor: Colors.blue,
        ),
      );

      await _fetchDashboardData();
    } on DioException catch (e) {
      if (!mounted) return;
      if (e.response?.statusCode == 401) return;

      developer.log(
        'Failed to end session: ${e.response?.statusCode} - ${e.response?.data}',
      );

      String errorMessage;
      if (e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout) {
        errorMessage = 'انتهت مهلة الاتصال بالخادم.';
      } else {
        errorMessage =
            e.response?.data?['message'] ??
            'فشل إنهاء الجلسة (${e.response?.statusCode})';
      }

      setState(() => _errorMessage = errorMessage);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('خطأ: $errorMessage'),
          backgroundColor: Colors.red,
        ),
      );
    } catch (error, stacktrace) {
      developer.log(
        'Error ending session: $error',
        error: error,
        stackTrace: stacktrace,
      );
      if (!mounted) return;
      setState(() => _errorMessage = 'خطأ في الاتصال عند إنهاء الجلسة');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_errorMessage!), backgroundColor: Colors.red),
      );
    } finally {
      if (mounted) setState(() => _isSessionLoading = false);
    }
  }

  // --- دالة تسجيل الاستراحة (مرقاة لمعمارية ApiClient) ---
  Future<void> _toggleBreak(String action) async {
    if (_isSessionLoading) return;
    setState(() {
      _isSessionLoading = true;
      _errorMessage = null;
    });

    try {
      await ApiClient.instance.put(
        '/driver/${widget.driverId}/sessions/break',
        data: {'action': action},
      );

      if (!mounted) return;

      // حفظ حالة الاستراحة محلياً
      // حفظ حالة الاستراحة محلياً
      final String breakStatus = (action == 'start') ? 'true' : 'false';
      await const FlutterSecureStorage().write(
        key: 'is_on_break',
        value: breakStatus,
      );

      // +++ حماية السياق بعد الـ await لمنع خطأ الـ async gaps +++
      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            action == 'start'
                ? 'تم بدء الاستراحة، تم إقفال شاشات البيع.'
                : 'تم إنهاء الاستراحة، يمكنك العودة للعمل.',
          ),
          backgroundColor: Colors.blue,
        ),
      );
      await _fetchDashboardData();
    } on DioException catch (e) {
      if (!mounted) return;
      if (e.response?.statusCode == 401) return;

      String errorMsg = e.response?.data?['message'] ?? 'فشل تسجيل الاستراحة';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('خطأ: $errorMsg'), backgroundColor: Colors.red),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('حدث خطأ في الاتصال'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSessionLoading = false);
    }
  }

  // --- +++ دالة مساعدة جديدة لجلب الموقع الحالي +++ ---
  Future<Position?> _getDeviceLocation() async {
    bool serviceEnabled;
    LocationPermission permission;

    developer.log("Checking location services...");
    // التحقق من تفعيل خدمات الموقع في الجهاز
    serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      developer.log("Location services are disabled.");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('الرجاء تفعيل خدمات الموقع (GPS) للمتابعة.'),
            backgroundColor: Colors.orange,
          ),
        );
      }
      return null; // لا يمكن المتابعة
    }

    developer.log("Checking location permissions...");
    // التحقق من أذونات الموقع
    permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      developer.log("Location permission denied, requesting permission...");
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        developer.log("Location permission denied after request.");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'تم رفض إذن الوصول للموقع. لا يمكن بدء الجلسة بدون موقع.',
              ),
              backgroundColor: Colors.red,
            ),
          );
        }
        return null; // لا يمكن المتابعة
      }
    }

    if (permission == LocationPermission.deniedForever) {
      developer.log("Location permission denied forever.");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'تم رفض إذن الوصول للموقع بشكل دائم. يرجى تفعيله من إعدادات التطبيق.',
            ),
            backgroundColor: Colors.red,
          ),
        );
      }
      // يمكنك إضافة فتح الإعدادات هنا لاحقاً
      return null; // لا يمكن المتابعة
    }

    // الأذونات ممنوحة والخدمة مفعلة، جلب الموقع
    developer.log("Location permissions granted, getting current position...");
    try {
      // +++ التعديل الجراحي: الاعتماد على آخر موقع معروف أولاً لتجنب تجميد الهاردوير +++
      Position? lastPosition = await Geolocator.getLastKnownPosition();
      if (lastPosition != null) {
        return lastPosition;
      }
      return await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.low,
      ).timeout(const Duration(seconds: 4));
    } on TimeoutException {
      developer.log("Location request timed out. Proceeding without GPS.");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'تأخر التقاط الـ GPS. سيتم بدء العمل بالاعتماد على آخر موقع معروف لتسهيل عملك.',
            ),
            backgroundColor: Colors.orange,
          ),
        );
      }
      return null; // +++ سيسمح هذا للتطبيق بفتح الجلسة وإرسال الطلب بدلاً من تجميد المندوب +++
    } catch (e) {
      developer.log("Error getting current position: $e");
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('حدث خطأ أثناء تحديد الموقع: ${e.toString()}'),
            backgroundColor: Colors.red,
          ),
        );
      }
      return null; // فشل جلب الموقع
    }
  }
  // --- +++ نهاية الدالة المساعدة +++ ---

  // ==========================================
  // دوال "المصافحة" (Handshake) للحوالات المعلقة
  // ==========================================
  bool _isCheckingTransfers = false;

  Future<void> _checkPendingTransfers() async {
    if (_isCheckingTransfers || !_isActiveSession || !mounted) return;
    _isCheckingTransfers = true;

    try {
      final response = await ApiClient.instance.get(
        '/driver/transfers/pending',
      );

      if (mounted) {
        final List<dynamic> transfers = response.data ?? [];
        if (transfers.isNotEmpty) {
          _showTransferDialog(transfers.first);
        }
      }
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) return;
      developer.log('API Error checking transfers: ${e.message}');
    } catch (e) {
      developer.log('Error checking transfers: $e');
    } finally {
      if (mounted) _isCheckingTransfers = false;
    }
  }

  void _showTransferDialog(Map<String, dynamic> transfer) {
    showDialog(
      context: context,
      barrierDismissible: false, // يمنع الضغط خارج النافذة لإغلاقها
      builder: (dialogContext) {
        final int deltaCartons = transfer['delta_cartons'] ?? 0;
        final String productName = transfer['product_name'] ?? 'منتج غير معروف';
        final bool isAddition = deltaCartons > 0;

        // +++ الدرع الحديدي الحديث: منع زر الرجوع (PopScope) +++
        return PopScope(
          canPop: false, // يمنع إغلاق الشاشة نهائياً بزر الرجوع
          child: AlertDialog(
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            title: Row(
              children: [
                Icon(
                  isAddition ? Icons.add_box : Icons.remove_circle_outline,
                  color: isAddition ? Colors.green : Colors.red,
                ),
                const SizedBox(width: 8),
                Text(
                  isAddition ? 'استلام بضاعة' : 'سحب بضاعة',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 18,
                  ),
                ),
              ],
            ),
            content: Text(
              isAddition
                  ? 'الإدارة أرسلت (${deltaCartons.abs()} كرتونة) من $productName لسيارتك. هل تؤكد استلامها لتدخل عهدتك؟'
                  : 'الإدارة تطلب سحب (${deltaCartons.abs()} كرتونة) من $productName من سيارتك. هل توافق؟',
              style: const TextStyle(fontSize: 16),
            ),
            actions: [
              TextButton(
                onPressed: () {
                  Navigator.pop(dialogContext);
                  _respondToTransfer(transfer['transfer_id'], 'rejected');
                },
                child: const Text(
                  'رفض ❌',
                  style: TextStyle(
                    color: Colors.red,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: isAddition ? Colors.green : Colors.blue,
                ),
                onPressed: () {
                  Navigator.pop(dialogContext);
                  _respondToTransfer(transfer['transfer_id'], 'accepted');
                },
                child: const Text(
                  'موافق ✅',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
              ),
            ],
          ), // إغلاق AlertDialog
        ); // إغلاق WillPopScope
      },
    );
  }

  Future<void> _respondToTransfer(int transferId, String responseStatus) async {
    try {
      await ApiClient.instance.put(
        '/driver/transfers/$transferId/respond',
        data: {'response': responseStatus},
      );

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('تم تسجيل الرد بنجاح. جاري التحديث...')),
      );
      _fetchDashboardData();
    } on DioException catch (e) {
      if (!mounted) return;
      if (e.response?.statusCode == 401) return;

      final errorMsg = e.response?.data?['message'] ?? 'فشل إرسال الرد السيرفر';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('خطأ: $errorMsg'), backgroundColor: Colors.red),
      );
    } catch (e) {
      developer.log('Error responding to transfer: $e');
      if (!mounted) return;
      // +++ فك الصمت وإخبار المندوب بوجود مشكلة تقنية +++
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('حدث خطأ في النظام أثناء معالجة ردك: $e'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  // --- دالة بناء الواجهة ---
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('اللوحة الرئيسية'),
        centerTitle: true,
        automaticallyImplyLeading: false, // يمنع ظهور زر الرجوع التلقائي
        actions: [
          // <-- تعريف actions مرة واحدة فقط
          // زر التحديث
          IconButton(
            onPressed: _fetchDashboardData, // دالة التحديث
            icon: const Icon(Icons.refresh),
            tooltip: 'تحديث البيانات',
          ),
          // زر تسجيل الخروج (مربوط بـ دالتك لتعرض التنبيه أولاً ثم تكلم العقل)
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'تسجيل الخروج',
            onPressed: _isActiveSession ? null : _logout,
          ),

          // --- نهاية زر تسجيل الخروج ---
        ], // <-- نهاية قائمة actions
      ),
      body: _buildDashboardContent(),
    );
  }

  // --- دالة بناء محتوى الـ Dashboard (تبقى كما هي من آخر تعديل) ---
  // --- تتضمن عرض البيانات المالية والمخزون بالشكل الجديد ---
  Widget _buildDashboardContent() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                'حدث خطأ: $_errorMessage',
                style: const TextStyle(color: Colors.red),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 10),
              ElevatedButton(
                onPressed: _fetchDashboardData,
                child: const Text('إعادة المحاولة'),
              ),
            ],
          ),
        ),
      );
    }
    String startTimeFormatted = '';
    if (_isActiveSession && _activeSessionStartTime != null) {
      try {
        final startTime = DateTime.parse(_activeSessionStartTime!).toLocal();
        startTimeFormatted = DateFormat('hh:mm a', 'ar').format(startTime);
      } catch (e) {
        developer.log(
          "Error parsing/formatting session start time for display: $e",
        );
        startTimeFormatted = "غير معروف";
      }
    }

    return RefreshIndicator(
      onRefresh: _fetchDashboardData,
      child: ListView(
        padding: const EdgeInsets.all(16.0),
        children: [
          Text(
            'أهلاً بك، $_driverName!',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            'المنطقة المخصصة: $_assignedRegion',
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
              _isActiveSession
                  ? 'جاري العمـل (بدأ الساعة: $startTimeFormatted)'
                  : 'اضغط لبدء العمل',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: _isActiveSession ? Colors.green[700] : Colors.red[700],
              ),
            ),
          ),
          const SizedBox(height: 15),
          Center(
            child: ElevatedButton.icon(
              icon:
                  _isSessionLoading
                      ? Container(
                        width: 24,
                        height: 24,
                        padding: const EdgeInsets.all(2.0),
                        child: const CircularProgressIndicator(
                          color: Colors.white,
                          strokeWidth: 3,
                        ),
                      )
                      : Icon(
                        _isActiveSession
                            ? Icons.stop_circle_outlined
                            : Icons.play_arrow,
                      ),
              label: Text(_isActiveSession ? 'إنهاء العمل' : 'بدء العمل'),
              // --- بداية الكود المُعدّل لـ onPressed (باستخدام الكود الخاص بك) ---
              onPressed:
                  _isSessionLoading
                      ? null // لا نغير شيئاً هنا، يبقى الزر معطلاً أثناء التحميل
                      : () async {
                        // <-- بداية الكود الجديد: حوّلنا الـ callback إلى async
                        // التحقق من حالة الجلسة لتحديد أي رسالة تأكيد وأي دالة نستدعي
                        if (_isActiveSession) {
                          // +++ منع إنهاء العمل أثناء الاستراحة +++
                          if (_isOnBreak) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text(
                                  'يجب إنهاء الاستراحة أولاً قبل إنهاء العمل!',
                                ),
                                backgroundColor: Colors.orange,
                              ),
                            );
                            return;
                          }
                          // --- الحالة: الجلسة نشطة (نريد إنهاء العمل) ---
                          final bool? confirmed = await _showConfirmationDialog(
                            context, // <-- تمرير الـ context
                            'إنهاء العمل؟', // العنوان
                            'هل أنت متأكد أنك تريد إنهاء جلسة العمل الحالية؟', // المحتوى
                          );
                          // إذا ضغط المستخدم "نعم، تأكيد" (confirmed == true)
                          if (confirmed == true) {
                            // استدعِ الدالة الأصلية لإنهاء العمل
                            _endWork(); // <-- استدعاء دالتك الأصلية
                          } else {
                            developer.log(
                              'End work cancelled by user.',
                            ); // طباعة اختيارية
                          }
                        } else {
                          // --- الحالة: لا يوجد جلسة نشطة (نريد بدء العمل) ---
                          final bool? confirmed = await _showConfirmationDialog(
                            context, // <-- تمرير الـ context
                            'بدء العمل؟', // العنوان
                            'هل أنت متأكد أنك تريد بدء جلسة عمل جديدة؟', // المحتوى
                          );
                          // إذا ضغط المستخدم "نعم، تأكيد" (confirmed == true)
                          if (confirmed == true) {
                            // استدعِ الدالة الأصلية لبدء العمل
                            _startWork(); // <-- استدعاء دالتك الأصلية
                          } else {
                            developer.log(
                              'Start work cancelled by user.',
                            ); // طباعة اختيارية
                          }
                        }
                      }, // <-- نهاية الكود الجديد لـ onPressed
              // --- نهاية الكود المُعدّل لـ onPressed ---
              style: ElevatedButton.styleFrom(
                backgroundColor:
                    _isActiveSession ? Colors.red[600] : Colors.green[600],
                padding: const EdgeInsets.symmetric(
                  horizontal: 30,
                  vertical: 12,
                ),
                textStyle: const TextStyle(fontSize: 16),
              ).copyWith(
                overlayColor: WidgetStateProperty.resolveWith<Color?>((
                  Set<WidgetState> states,
                ) {
                  if (states.contains(WidgetState.pressed)) {
                    return _isActiveSession
                        ? Colors.red[800]
                        : Colors.green[800];
                  }
                  return null; // Defer to the default overlay format
                }),
              ),
            ),
          ),
          // +++ زر الاستراحة (يظهر فقط إذا الجلسة نشطة) +++
          if (_isActiveSession) ...[
            const SizedBox(height: 10),
            Center(
              child: ElevatedButton.icon(
                onPressed:
                    _isSessionLoading
                        ? null
                        : () => _toggleBreak(_isOnBreak ? 'end' : 'start'),
                icon: Icon(
                  _isOnBreak
                      ? Icons.free_breakfast_outlined
                      : Icons.free_breakfast,
                ),
                label: Text(_isOnBreak ? 'إنهاء الاستراحة' : 'بدء الاستراحة'),
                style: ElevatedButton.styleFrom(
                  backgroundColor:
                      _isOnBreak ? Colors.orange[700] : Colors.blue[600],
                  padding: const EdgeInsets.symmetric(
                    horizontal: 30,
                    vertical: 12,
                  ),
                  textStyle: const TextStyle(fontSize: 16),
                ),
              ),
            ),
          ],

          // ++++++++++++++++++++++++++++++++++++++++
          const Divider(height: 30, thickness: 1),
          Text('ملخص الجولة:', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Text(
            ' - الزيارات المكتملة: ${_counts['total_completed'] ?? 0}',
            style: const TextStyle(fontSize: 16),
          ),
          Text(
            ' - الزيارات الناجحة (مبيعات): ${_counts['sales_in_completed'] ?? 0}',
            style: const TextStyle(fontSize: 16),
          ),
          Text(
            ' - الزيارات المعلقة: ${_counts['total_pending'] ?? 0}',
            style: const TextStyle(fontSize: 16),
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
                  'إجمالي كاش المبيعات: ${_totalSalesCash?.toStringAsFixed(2) ?? '--'} د.أ',
                  style: const TextStyle(fontSize: 16),
                ),
                SizedBox(height: 4),
                Text(
                  'إجمالي الذمم المحصلة: (${_debtPaymentsCount ?? 0}) ${_totalDebtPaid?.toStringAsFixed(2) ?? '--'} د.أ',
                  style: const TextStyle(fontSize: 16),
                ),
                SizedBox(height: 4),
                Text(
                  'إجمالي الكاش المستلم: ${_totalCashOverall?.toStringAsFixed(2) ?? '--'} د.أ',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                ),
              ],
            ),
          ),
          // --- زر عرض قائمة الزيارات (تم رفعه للأعلى) ---
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
                  developer.log(
                    'Returned from VisitListScreen, refreshing dashboard...',
                  );
                  _fetchDashboardData();
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

          // --- قسم المخزون الدائم (أصبح في الأسفل) ---
          const Divider(height: 30, thickness: 1),
          Text(
            'مخزون سيارة المندوب:',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),

          if (_inventoryList.isEmpty)
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

          if (_inventoryList.isNotEmpty)
            ..._inventoryList.map((item) {
              // حساب المباع برمجياً
              int starting = item['starting_cartons'] ?? 0;
              int remaining = item['remaining_cartons'] ?? 0;
              int sold = starting - remaining;

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
                        '${item['product_name']}',
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
                            'الاستلام: $starting كرتونة',
                            style: const TextStyle(fontSize: 14),
                          ),
                          Text(
                            'المباع: $sold كرتونة',
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
                        'المتبقي: $remaining كرتونة، ${item['remaining_packs']} باكيت',
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
        ], // نهاية الـ children
      ), // نهاية الـ ListView
    ); // نهاية الـ RefreshIndicator
  } // نهاية دالة _buildDashboardContent
} // نهاية كلاس _DashboardScreenState
      // --- نهاية قسم المخزون ---