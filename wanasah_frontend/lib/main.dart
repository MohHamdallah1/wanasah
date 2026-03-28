import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart'; // استيراد الحزمة
import 'package:intl/date_symbol_data_local.dart'; // استيراد لتهيئة التواريخ العربية
// --- +++ إضافة استيراد لدعم localizations +++ ---
import 'package:flutter_localizations/flutter_localizations.dart';
// ---------------------------------------------
import 'dart:developer' as developer;
// استيراد الشاشات (تأكد من المسارات الصحيحة)
import 'screens/login_screen.dart';
import 'screens/dashboard_screen.dart';

// تعريف كائن التخزين بشكل عام للاستخدام في main
const storage = FlutterSecureStorage();

// جعل دالة main غير متزامنة async
Future<void> main() async {
  // التأكد من تهيئة Flutter أولاً قبل استخدام await
  WidgetsFlutterBinding.ensureInitialized();

  // تهيئة دعم اللغة العربية للتاريخ (مهم لـ intl)
  await initializeDateFormatting('ar', null);

  // --- التحقق من وجود التوكن و ID السائق ---
  String? token;
  String? driverIdString;
  int? driverId;
  Widget initialScreen; // الويدجت التي سيبدأ بها التطبيق

  try {
    token = await storage.read(key: 'auth_token');
    driverIdString = await storage.read(key: 'driver_id');

    if (token != null && driverIdString != null) {
      driverId = int.tryParse(driverIdString);
      if (driverId != null) {
        // يوجد توكن و ID صالح، ابدأ بلوحة التحكم
        developer.log("Found valid token and driver ID ($driverId), starting Dashboard.");
        // DashboardScreen ليست const لأنها تأخذ driverId
        initialScreen = DashboardScreen(driverId: driverId); 
      } else {
        developer.log("Found token but invalid driver ID string: $driverIdString. Clearing storage.");
        await storage.deleteAll();
        initialScreen = const LoginScreen();
      }
    } else {
      developer.log("No valid token/driver ID found, starting Login.");
      initialScreen = const LoginScreen();
    }
  } catch (e) {
    developer.log("Error reading from secure storage: $e. Starting Login.");
    initialScreen = const LoginScreen();
    // await storage.deleteAll(); // يمكنك إلغاء التعليق لمسح التخزين عند الخطأ
  }
  // ------------------------------------

  // تشغيل التطبيق مع تحديد الشاشة الأولى
  // تم إزالة const من MyApp لأن initialScreen قد لا تكون const
  runApp(MyApp(initialScreen: initialScreen)); 
}

// --- تعديل MyApp ليقبل الشاشة الأولى ---
class MyApp extends StatelessWidget {
  // --- +++ إضافة final وإزالة const من الكونستركتور +++ ---
  final Widget initialScreen; 
  const MyApp({required this.initialScreen, super.key});
  // -----------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Wanasah App', 
      theme: ThemeData(
        primarySwatch: Colors.teal, 
        visualDensity: VisualDensity.adaptivePlatformDensity,
        fontFamily: 'Cairo', 
      ),
      debugShowCheckedModeBanner: false, 
      
      // --- +++ إضافة localizationsDelegates الضرورية +++ ---
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      // ----------------------------------------------------
      
      supportedLocales: const [ 
          Locale('ar', ''), // تحديد العربية كلغة مدعومة
          // Locale('en', ''), // يمكنك إضافة الإنجليزية إذا أردت
        ], 
      locale: const Locale('ar', ''), // تحديد العربية كلغة افتراضية للواجهات
      
      // تحديد الشاشة الأولى بناءً على نتيجة التحقق من التوكن
      home: initialScreen, 
    );
  }
}
// --- نهاية MyApp المعدلة ---