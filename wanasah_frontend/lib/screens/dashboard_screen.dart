import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:developer' as developer;
import 'package:intl/intl.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
// استيراد الملف المساعد للتوثيق (تأكد من المسار الصحيح)
import '../services/auth_utils.dart';
// استيراد شاشة الدخول (للعودة إليها عند خطأ 401)
import 'login_screen.dart'; 
import 'visit_list_screen.dart';
import 'package:geolocator/geolocator.dart';
import 'dart:async'; 
import 'dart:io'; 

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
  Map<String, int> _counts = { 'total_pending': 0, 'total_completed': 0, 'sales_in_completed': 0, };
  double? _totalSalesCash;
  double? _totalDebtPaid;
  int? _debtPaymentsCount;
  double? _totalCashOverall;
  int? _startingCartons;
  int? _remainingCartons;
  // ignore: prefer_final_fields
  bool _isActiveSession = false;
  String? _activeSessionStartTime;
  bool _isSessionLoading = false; // لتحميل أزرار البدء/الإنهاء
  int? _remainingPacks;
  // لا نحتاج لتعريف storage هنا لأن الدوال المساعدة تستخدمه داخلياً

  // --- دالة مساعدة لعرض مربع حوار التأكيد ---
Future<bool?> _showConfirmationDialog(BuildContext context, String title, String content) async {
  // استخدام showDialog لعرض مربع حوار، ونوعه bool لأنه سيعيد true أو false
  return await showDialog<bool>(
    context: context,
    barrierDismissible: false, // يجب على المستخدم الضغط على زر للخروج
    builder: (BuildContext dialogContext) { // dialogContext هو context الخاص بمربع الحوار
      return AlertDialog(
        title: Text(title),       // عنوان مربع الحوار
        content: Text(content),   // محتوى الرسالة
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
  final bool? confirmed = await _showConfirmationDialog( // استخدام نفس دالة التأكيد
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

      // الانتقال لشاشة تسجيل الدخول وإزالة كل الشاشات السابقة
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (context) => const LoginScreen()), // اذهب لشاشة الدخول
        (Route<dynamic> route) => false, // هذا الشرط يحذف كل الطرق السابقة
      );

    } catch (e) {
      developer.log('Error during logout: $e');
      // عرض رسالة خطأ إذا فشل المسح أو الانتقال
       if(mounted){ ScaffoldMessenger.of(context).showSnackBar(
         const SnackBar(content: Text('حدث خطأ أثناء تسجيل الخروج.'), backgroundColor: Colors.red),
       );}
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

  // --- دالة جلب بيانات الـ Dashboard  ---
  Future<void> _fetchDashboardData() async {
    if (!mounted) return;

    // تعيين حالة التحميل دائماً عند بدء الجلب
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    // تأكد من أن widget.driverId متوفر وأن baseUrl صحيح
    final url = Uri.parse('http://10.0.2.2:5000/driver/${widget.driverId}/dashboard');

    String? errorMsgForState; // متغير محلي لتخزين رسائل الخطأ

    try {
      final headers = await getAuthenticatedHeaders(needsContentType: false);
      final response = await http.get(url, headers: headers).timeout(const Duration(seconds: 15));

      if (!mounted) return; // التحقق بعد await

      if (response.statusCode == 401) {
        await handleUnauthorized(context);
        return; // الخروج بعد الانتقال
      }

      if (response.statusCode == 200) {
        try {
          final Map<String, dynamic> data = jsonDecode(response.body);

          // استخلاص بيانات الجلسة النشطة
          final Map<String, dynamic>? sessionData = data['active_session'] as Map<String, dynamic>?;
          bool sessionIsActive = (sessionData != null);

          // استخلاص باقي البيانات
          final Map<String, dynamic>? financials = data['financials'] as Map<String, dynamic>?;
          final double totalSalesCash = (financials?['total_sales_cash'] as num?)?.toDouble() ?? 0.0;
          final double totalDebtPaid = (financials?['total_debt_paid'] as num?)?.toDouble() ?? 0.0;
          final int debtPaymentsCount = financials?['debt_payments_count'] as int? ?? 0;
          final double totalCashOverall = (financials?['total_cash_overall'] as num?)?.toDouble() ?? 0.0;
          String? startTimeStr; int? startCartons; int? remainingCartons; int? remainingPacks;
          if (sessionData != null) {
             startTimeStr = sessionData['start_time'] as String?;
             startCartons = sessionData['starting_cartons'] as int?;
             remainingCartons = sessionData['remaining_cartons'] as int?;
             remainingPacks = sessionData['remaining_packs'] as int?;
          } else {
             startTimeStr = null; startCartons = null; remainingCartons = null; remainingPacks = null;
          }
          final Map<String, dynamic>? countsData = data['counts'] as Map<String, dynamic>?;
          final Map<String, int> counts = {
             'total_pending': countsData?['total_pending'] as int? ?? 0,
             'total_completed': countsData?['total_completed'] as int? ?? 0,
             'sales_in_completed': countsData?['sales_in_completed'] as int? ?? 0,
           };

          // تحديث الحالة
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
            _startingCartons = startCartons;
            _remainingCartons = remainingCartons;
            _remainingPacks = remainingPacks;
            _isLoading = false;
            _errorMessage = null;
          });

        } catch (decodeError, stacktrace) { // خطأ فك التشفير
          // --- أبقينا على طباعة أخطاء فك التشفير لأنها مفيدة ---
          developer.log('Dashboard JSON Decode EXCEPTION: ${decodeError.toString()}', name: 'DashboardFetch', error: decodeError, stackTrace: stacktrace);
          // --------------------------------------------------
          errorMsgForState = 'خطأ في فهم استجابة الخادم.';
        }

      } else { // رموز الحالة الأخرى
          // --- أبقينا على طباعة أخطاء استجابة السيرفر ---
          developer.log('Dashboard fetch failed: Status ${response.statusCode}, Body: ${response.body}', name: 'DashboardFetch');
          // -------------------------------------------
          errorMsgForState = 'فشل تحميل البيانات (${response.statusCode})';
      }
    } catch (error, stacktrace) { // أخطاء الشبكة والمهلة وغيرها
      // --- أبقينا على طباعة أخطاء الشبكة العامة ---
      developer.log('Dashboard Network/Other EXCEPTION: ${error.toString()}', name: 'DashboardFetch', error: error, stackTrace: stacktrace);
      // -----------------------------------------
      if (!mounted) return;
      errorMsgForState = 'خطأ في الاتصال بالخادم.';
      if (error is TimeoutException) { errorMsgForState = 'انتهت مهلة الاتصال بالخادم.'; }
      else if (error is SocketException) { errorMsgForState = 'خطأ في الشبكة، تأكد من اتصالك.';}
    } finally {
       if (mounted && (_isLoading || errorMsgForState != null)) {
          setState(() {
            _isLoading = false;
            if (errorMsgForState != null) {
              _errorMessage = errorMsgForState;
            }
          });
       }
    }
  }
  // --- نهاية دالة جلب بيانات الـ Dashboard ---


  // --- دالة بدء العمل (معدلة لتشمل جلب الموقع وإرساله) ---
Future<void> _startWork() async {
  // منع الضغط المتكرر
  if (_isSessionLoading) return;

  setState(() { _isSessionLoading = true; }); // بدء التحميل

  developer.log("Start Work button pressed. Attempting to get location first...");

  Position? currentPosition; // لتخزين الموقع
  String? errorMsg; // لتخزين أي رسالة خطأ

  try {
    // --- الخطوة 1: جلب الموقع ---
    currentPosition = await _getDeviceLocation();

    // إذا فشل جلب الموقع (لأي سبب)، أوقف العملية وأظهر الخطأ (تم عرضه في _getDeviceLocation)
    if (currentPosition == null) {
      developer.log("Failed to get location, aborting start work session.");
      // لا تقم بتحديث الحالة هنا، رسالة الخطأ ظهرت بالفعل
      // setState(() { _isSessionLoading = false; }); // سيتم في finally
      return; // اخرج من الدالة
    }

    developer.log("Location obtained: Lat: ${currentPosition.latitude}, Lng: ${currentPosition.longitude}. Proceeding to start session API call...");

    // --- الخطوة 2: استدعاء API بدء الجلسة مع إرسال الإحداثيات ---
    final url = Uri.parse('http://10.0.2.2:5000/driver/${widget.driverId}/sessions/start'); // تأكد من driverId
    final headers = await getAuthenticatedHeaders(); // يفترض أنها تضيف Content-Type للـ POST

    // بناء الجسم متضمناً الإحداثيات
    final body = jsonEncode({
      'latitude': currentPosition.latitude,
      'longitude': currentPosition.longitude,
    });

    final response = await http.post(
      url,
      headers: headers,
      body: body,
    ).timeout(const Duration(seconds: 20)); // Timeout

    if (!mounted) return;

    // --- الخطوة 3: معالجة الرد وتحديث الواجهة ---
    if (response.statusCode == 201 || response.statusCode == 409) { // 201=جديدة, 409=موجودة بالفعل
      // نجح بدء الجلسة (أو وجدت جلسة نشطة)، أعد تحميل بيانات الداشبورد لعرضها
      developer.log("Session started or already active. Fetching dashboard data...");
      await _fetchDashboardData(); // <-- مهم جداً لتحديث الواجهة
      if (response.statusCode == 201) {
         if (mounted) {ScaffoldMessenger.of(context).showSnackBar(
           const SnackBar(content: Text('تم بدء جلسة العمل بنجاح!'), backgroundColor: Colors.green),
         );}
      } else {
        if (mounted) {
           ScaffoldMessenger.of(context).showSnackBar(
           const SnackBar(content: Text('يوجد جلسة عمل نشطة بالفعل لهذا اليوم.'), backgroundColor: Colors.blue),
         );}
      }
    } else if (response.statusCode == 401) {
        await handleUnauthorized(context);
    } else {
      // خطأ آخر من السيرفر
       developer.log('Failed to start session: ${response.statusCode} - ${response.body}');
       errorMsg = 'فشل بدء جلسة العمل (${response.statusCode})';
       try { final errorData = jsonDecode(response.body); if (errorData is Map && errorData.containsKey('message')) { errorMsg = errorData['message']; } } catch (_) {}
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar( content: Text('خطأ: $errorMsg'), backgroundColor: Colors.red, ));
        }
    }

  } catch (e, s) { // التقاط أي خطأ (من جلب الموقع أو الاتصال)
     developer.log('Error during start work process: $e', error: e, stackTrace: s);
     errorMsg = 'حدث خطأ: ${e.toString()}';
     // يمكنك تخصيص رسائل الخطأ هنا لأنواع مختلفة من Exceptions
     if (e is TimeoutException) { errorMsg = 'انتهت مهلة الاتصال بالخادم.'; }
     // ... (أنواع أخرى إذا أردت) ...

     if (mounted) {
       ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMsg), backgroundColor: Colors.red),
       );
     }
  } finally {
     // إيقاف التحميل دائماً في النهاية
     if (mounted) {
       setState(() { _isSessionLoading = false; });
     }
     developer.log("Finished start work attempt.");
  }
}
// --- نهاية دالة بدء العمل ---

  // --- دالة إنهاء العمل (معدلة لاستخدام التوكن والتحقق من 401) ---
  Future<void> _endWork() async {
      if (_isSessionLoading) return;
      setState(() { _isSessionLoading = true; _errorMessage = null; });
      final url = Uri.parse('http://10.0.2.2:5000/driver/${widget.driverId}/sessions/end');
      developer.log('Ending work session: $url');
      try {
          // +++ استخدام الدالة المساعدة للحصول على الهيدرز +++
          final headers = await getAuthenticatedHeaders(needsContentType: false);
          final response = await http.put(url, headers: headers).timeout(const Duration(seconds: 15));
          // ++++++++++++++++++++++++++++++++++++++++++++++

          if (!mounted) return;

          // +++ التحقق من 401 واستخدام الدالة المساعدة +++
           if (response.statusCode == 401) {
             await handleUnauthorized(context);
             setState(() { _isSessionLoading = false; });
             return;
           }
          // ++++++++++++++++++++++++++++++++++++++++++++++

          if (response.statusCode == 200) {
             // ... (نفس كود معالجة النجاح) ...
              developer.log('End session response: ${response.body}');
              await _fetchDashboardData();
              if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('تم إنهاء جلسة العمل بنجاح.'), backgroundColor: Colors.blue)); }
          } else {
             // ... (نفس كود معالجة الأخطاء الأخرى) ...
              developer.log('Failed to end session: ${response.statusCode} - ${response.body}'); String errorMessage = 'فشل إنهاء الجلسة (${response.statusCode})'; try { final errorData = jsonDecode(response.body); if (errorData is Map && errorData.containsKey('message')) { errorMessage = errorData['message']; }} catch (_) {} setState(() { _errorMessage = errorMessage; }); ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('خطأ: $errorMessage'), backgroundColor: Colors.red));
          }
      } catch(error, stacktrace) {
         // ... (نفس كود معالجة أخطاء الاتصال) ...
          developer.log('Error ending session: ${error.toString()}', error: error, stackTrace: stacktrace); if (!mounted) return; setState(() { _errorMessage = 'خطأ في الاتصال عند إنهاء الجلسة'; }); ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_errorMessage!), backgroundColor: Colors.red));
      } finally {
          if (mounted) { setState(() { _isSessionLoading = false; }); }
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
          const SnackBar(content: Text('الرجاء تفعيل خدمات الموقع (GPS) للمتابعة.'), backgroundColor: Colors.orange),
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
            const SnackBar(content: Text('تم رفض إذن الوصول للموقع. لا يمكن بدء الجلسة بدون موقع.'), backgroundColor: Colors.red),
          );
        }
        return null; // لا يمكن المتابعة
      }
    }

    if (permission == LocationPermission.deniedForever) {
      developer.log("Location permission denied forever.");
       if (mounted) {
         ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('تم رفض إذن الوصول للموقع بشكل دائم. يرجى تفعيله من إعدادات التطبيق.'), backgroundColor: Colors.red),
        );
       }
       // يمكنك إضافة فتح الإعدادات هنا لاحقاً
       return null; // لا يمكن المتابعة
    }

    // الأذونات ممنوحة والخدمة مفعلة، جلب الموقع
    developer.log("Location permissions granted, getting current position...");
    try {
       return await Geolocator.getCurrentPosition(
          desiredAccuracy: LocationAccuracy.high // طلب دقة عالية
       );
    } catch (e) {
       developer.log("Error getting current position: $e");
        if (mounted) {
         ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('حدث خطأ أثناء تحديد الموقع: ${e.toString()}'), backgroundColor: Colors.red),
        );
       }
       return null; // فشل جلب الموقع
    }
  }
  // --- +++ نهاية الدالة المساعدة +++ ---

  // --- دالة بناء الواجهة (تبقى كما هي) ---
@override
Widget build(BuildContext context) {
  return Scaffold(
    appBar: AppBar(
      title: const Text('اللوحة الرئيسية'),
      centerTitle: true,
      automaticallyImplyLeading: false, // يمنع ظهور زر الرجوع التلقائي
      actions: [ // <-- تعريف actions مرة واحدة فقط
        // زر التحديث
        IconButton(
          onPressed: _fetchDashboardData, // دالة التحديث
          icon: const Icon(Icons.refresh),
          tooltip: 'تحديث البيانات',
        ),
    // زر تسجيل الخروج (معدل ليكون مشروطاً)
        IconButton(
          icon: const Icon(Icons.logout),
          tooltip: 'تسجيل الخروج',
          // --- التعديل هنا ---
          // عطّل الزر (null) إذا كانت الجلسة نشطة (_isActiveSession == true)
          // وشغّل دالة _logout إذا لم تكن نشطة (_isActiveSession == false)
          onPressed: _isActiveSession
              ? null  // <-- اجعل onPressed فارغاً (معطلاً) إذا كانت الجلسة نشطة
              : _logout, // <-- استدعِ _logout فقط إذا لم تكن الجلسة نشطة
          // ------------------
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

// ... (نفس كود _buildDashboardContent الذي يعرض كل البيانات المالية والمخزون) ...

if (_isLoading) { return const Center(child: CircularProgressIndicator()); }

if (_errorMessage != null) { return Center( child: Padding( padding: const EdgeInsets.all(16.0), child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [ Text('حدث خطأ: $_errorMessage', style: const TextStyle(color: Colors.red), textAlign: TextAlign.center,), const SizedBox(height: 10), ElevatedButton(onPressed: _fetchDashboardData, child: const Text('إعادة المحاولة')) ]), ), ); }

String startTimeFormatted = ''; if (_isActiveSession && _activeSessionStartTime != null) { try { final startTime = DateTime.parse(_activeSessionStartTime!).toLocal(); startTimeFormatted = DateFormat('hh:mm a', 'ar').format(startTime); } catch (e) { developer.log("Error parsing/formatting session start time for display: $e"); startTimeFormatted = "غير معروف"; } }

return RefreshIndicator(
  onRefresh: _fetchDashboardData,
  child: ListView(
    padding: const EdgeInsets.all(16.0),
    children: [
      Text('أهلاً بك، $_driverName!', style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 8),
      Text('المنطقة المخصصة: $_assignedRegion', style: TextStyle(fontSize: 17, color: Colors.blueGrey[700])),
      const SizedBox(height: 8),
      Text('تاريخ اليوم: ${DateFormat('EEEE, d MMMM Backdrop', 'ar').format(DateTime.now())}', style: TextStyle(fontSize: 15, color: Colors.grey[600])), // Corrected DateFormat pattern
      const Divider(height: 30, thickness: 1),
      Center(
        child: Text(
          _isActiveSession ? 'جاري العمـل (بدأ الساعة: $startTimeFormatted)' : 'اضغط لبدء العمل',
          style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.bold,
              color: _isActiveSession ? Colors.green[700] : Colors.red[700]),
        ),
      ),
      const SizedBox(height: 15),
      Center(
        child: ElevatedButton.icon(
          icon: _isSessionLoading
              ? Container(
                  width: 24,
                  height: 24,
                  padding: const EdgeInsets.all(2.0),
                  child: const CircularProgressIndicator(
                      color: Colors.white, strokeWidth: 3))
              : Icon(_isActiveSession ? Icons.stop_circle_outlined : Icons.play_arrow),
          label: Text(_isActiveSession ? 'إنهاء العمل' : 'بدء العمل'),
          // --- بداية الكود المُعدّل لـ onPressed (باستخدام الكود الخاص بك) ---
          onPressed: _isSessionLoading
            ? null // لا نغير شيئاً هنا، يبقى الزر معطلاً أثناء التحميل
            : () async { // <-- بداية الكود الجديد: حوّلنا الـ callback إلى async
                // التحقق من حالة الجلسة لتحديد أي رسالة تأكيد وأي دالة نستدعي
                if (_isActiveSession) {
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
                    developer.log('End work cancelled by user.'); // طباعة اختيارية
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
                    developer.log('Start work cancelled by user.'); // طباعة اختيارية
                  }
                }
              }, // <-- نهاية الكود الجديد لـ onPressed
          // --- نهاية الكود المُعدّل لـ onPressed ---
          style: ElevatedButton.styleFrom(
            backgroundColor: _isActiveSession ? Colors.red[600] : Colors.green[600],
            padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 12),
            textStyle: const TextStyle(fontSize: 16)
          ).copyWith(
            overlayColor: WidgetStateProperty.resolveWith<Color?>(
              (Set<WidgetState> states) {
                if (states.contains(WidgetState.pressed)) {
                  return _isActiveSession ? Colors.red[800] : Colors.green[800];
                }
                return null; // Defer to the default overlay format
              },
            ),
          )
        )
      ),
      const Divider(height: 30, thickness: 1),
      Text('ملخص الجولة:', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 12),
      Text(' - الزيارات المكتملة: ${_counts['total_completed'] ?? 0}', style: const TextStyle(fontSize: 16)),
      Text(' - المحلات المستلمة: ${_counts['sales_in_completed'] ?? 0}', style: const TextStyle(fontSize: 16)),
      Text(' - الزيارات المعلقة: ${_counts['total_pending'] ?? 0}', style: const TextStyle(fontSize: 16)),
      const SizedBox(height: 15),
      Text('الملخص المالي:', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 12),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('إجمالي كاش المبيعات: ${_totalSalesCash?.toStringAsFixed(2) ?? '--'} د.أ', style: const TextStyle(fontSize: 16)),
            SizedBox(height: 4),
            Text('إجمالي الذمم المحصلة: (${_debtPaymentsCount ?? 0}) ${_totalDebtPaid?.toStringAsFixed(2) ?? '--'} د.أ', style: const TextStyle(fontSize: 16)),
            SizedBox(height: 4),
            Text(
              'إجمالي الكاش المستلم: ${_totalCashOverall?.toStringAsFixed(2) ?? '--'} د.أ',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
            ),
          ],
        ),
      ),
      if (_isActiveSession && _startingCartons != null && _remainingCartons != null) ...[
  const Divider(height: 30, thickness: 1),
  Text('مخزون الكراتين والباكيتات:', style: Theme.of(context).textTheme.titleLarge),
  const SizedBox(height: 12),
  Padding(
    padding: const EdgeInsets.symmetric(horizontal: 4.0),
    child: Column( // أو يمكنك استخدام Row إذا أردت عرضهم بنفس السطر
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'مخزون البداية: ${_startingCartons ?? '--'} كرتونة',
          style: const TextStyle(fontSize: 16)
        ),
        const SizedBox(height: 4), // مسافة صغيرة
        // --- تعديل هنا لعرض الكراتين والباكيتات المتبقية ---
        Text(
          'المخزون المتبقي: ${_remainingCartons ?? '--'} كرتونة، ${_remainingPacks ?? '0'} باكيت',
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueAccent), // تنسيق مميز للمتبقي
        ),
            ],
          ),
        ),
      ],
      const Divider(height: 30, thickness: 1),
      Center(
        child: ElevatedButton.icon(
          icon: const Icon(Icons.list_alt_rounded),
          label: const Text('عرض قائمة زيارات اليوم'),
          onPressed: () {
            Navigator.push(
              context,
              MaterialPageRoute(
                builder: (context) => VisitListScreen(driverId: widget.driverId),
              ),
            ).then((_) {
                developer.log('Returned from VisitListScreen, refreshing dashboard...');
                _fetchDashboardData();
            });
          },
          style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
              textStyle: const TextStyle(fontSize: 16)
          ),
        ),
      ),
      const SizedBox(height: 20),
    ],
  ),
);
}
} // نهاية كلاس _DashboardScreenState