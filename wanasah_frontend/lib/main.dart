// File: lib/main.dart
//
// نقطة دخول التطبيق — نظيفة ومُخفَّفة.
// لا await لقراءة Storage هنا — هذا دور AuthBloc عبر SplashScreen.

import 'dart:ui' as ui;
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // +++ مكتبة التحكم بالنظام +++
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:sentry_flutter/sentry_flutter.dart'; // Step 5.2c: Flutter Sentry integration

import 'blocs/auth/auth_bloc.dart';
import 'core/network/api_client.dart';
import 'screens/splash_screen.dart';
import 'screens/login_screen.dart'; // +++ الشاشة التي سنطرد المستخدم إليها +++
import 'blocs/dashboard/dashboard_bloc.dart';
import 'blocs/auth/auth_event.dart'; // +++ لإرسال حدث الخروج +++
import 'blocs/auth/auth_state.dart'; // +++ للاستماع لحالة الخروج +++
import 'package:flutter_dotenv/flutter_dotenv.dart'; // +++ استيراد مكتبة البيئة +++

/// navigatorKey عالمي — مُشترَك بين MaterialApp وApiClient
/// حتى يتمكن AuthInterceptor من التنقل بدون BuildContext.
final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

// Step 4.5b: Global error handler for unhandled asynchronous errors (crashes outside Flutter's tree)
void _onPlatformError(Object error, StackTrace stack) {
  debugPrint('═══════════════ PLATFORM ASYNC CRASH ═══════════════');
  debugPrint('ERROR: $error');
  debugPrint('STACK: $stack');
  debugPrint('═══════════════════════════════════════════════════');
  Sentry.captureException(error, stackTrace: stack);
}

// Step 4.5b: Global handler for Flutter framework errors (build/layout failures)
void _onFlutterError(FlutterErrorDetails details) {
  debugPrint('═══════════════ FLUTTER FRAMEWORK CRASH ═══════════════');
  debugPrint('EXCEPTION: ${details.exception}');
  debugPrint('STACK: ${details.stack}');
  if (details.library != null) {
    debugPrint('LIBRARY: ${details.library}');
  }
  debugPrint('════════════════════════════════════════════════════════');
  Sentry.captureException(details.exception, stackTrace: details.stack);
  // Allow default Flutter error handling in debug mode (red screen)
  if (kDebugMode) {
    FlutterError.presentError(details);
  }
}

Future<void> main() async {
  // 1. ضمان تهيئة Flutter قبل أي async
  WidgetsFlutterBinding.ensureInitialized();

  // Step 4.5b: Install global error handlers for both sync and async crashes
  FlutterError.onError = _onFlutterError;
  ui.PlatformDispatcher.instance.onError = (error, stack) {
    _onPlatformError(error, stack);
    return true; // We've handled it; prevent default crash dialog
  };

  // 2. تهيئة دعم التاريخ العربي (intl)
  await initializeDateFormatting('ar', null);

  // +++ درع الإقلاع: حماية التطبيق من الانهيار المميت في حال فقدان ملف البيئة في الـ Production +++
  try {
    await dotenv.load(fileName: ".env");
  } catch (_) {
    debugPrint('⚠️ تنبيه: ملف .env غير موجود. سيتم استخدام الروابط الافتراضية.');
  }

  // 3. تهيئة Dio / ApiClient مع زر الإنذار (Callback)
  ApiClient.init(
    onUnauthorized: () {
      // عندما ينتهي التوكن، نخبر العقل المدبر (AuthBloc) فوراً
      final context = navigatorKey.currentContext;
      if (context != null) {
        context.read<AuthBloc>().add(const LogoutEvent());
      }
    },
  );

  // 4. تشغيل التطبيق محاطاً بـ Sentry لرصد الأعطال (خطوة 5.2c)
  await SentryFlutter.init(
    (options) {
      options.dsn = dotenv.env['SENTRY_DSN'] ?? '';
      options.tracesSampleRate = 0.1;
    },
    appRunner: () => runApp(const MyApp()),
  );
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    // +++ دمج العقول المدبرة في نقطة واحدة لتغذية التطبيق بالكامل (MultiProvider) +++
    return MultiBlocProvider(
      providers: [
        BlocProvider<AuthBloc>(create: (_) => AuthBloc()),
        BlocProvider<DashboardBloc>(create: (_) => DashboardBloc()),
      ],
      child: MaterialApp(
        title: 'Wanasah App',
        navigatorKey: navigatorKey,
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          primarySwatch: Colors.teal,
          // +++ فرض الشفافية العالمية على كل الأسطح المحتملة +++
          scaffoldBackgroundColor: Colors.transparent,
          canvasColor: Colors.white, 
          visualDensity: VisualDensity.adaptivePlatformDensity,
          fontFamily: 'Cairo',
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.transparent,
            elevation: 0,
            centerTitle: true,
            iconTheme: IconThemeData(color: Colors.black87),
            titleTextStyle: TextStyle(
              color: Colors.black87,
              fontWeight: FontWeight.bold,
              fontSize: 18,
            ),
          ),
        ),

        // دعم اللغة العربية
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [Locale('ar', '')],
        locale: const Locale('ar', ''),

        // +++ الهندسة البصرية الموحدة 2026: منع تسريب التطبيق تحت أزرار النظام +++
        builder: (context, child) {
          return AnnotatedRegion<SystemUiOverlayStyle>(
            value: const SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              statusBarIconBrightness: Brightness.dark,
              systemNavigationBarColor: Colors.white, // +++ جعل الشريط السفلي صلباً وأبيض +++
              systemNavigationBarIconBrightness: Brightness.dark,
              systemNavigationBarDividerColor: Colors.transparent,
            ),
            child: SafeArea(
              top: false,
              bottom: true, // +++ إجبار التطبيق على الانتهاء قبل أزرار النظام +++
              child: Material(
                color: Colors.white,
                child: Stack(
                  children: [
                    // الطبقة 0: التدرج اللوني (يتحرك الآن داخل حدود الـ SafeArea فقط)
                    Positioned.fill(
                      child: Container(
                        decoration: const BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [
                              Color.fromARGB(255, 194, 201, 173),
                              Color.fromARGB(255, 117, 179, 97),
                              Color.fromARGB(255, 255, 255, 255),
                            ],
                            stops: [0.0, 0.3, 0.8],
                          ),
                        ),
                      ),
                    ),
                    // الطبقة 1: المراقب والشاشات
                    BlocListener<AuthBloc, AuthState>(
                      listener: (context, state) {
                        if (state is AuthUnauthenticated) {
                          navigatorKey.currentState?.pushAndRemoveUntil(
                            MaterialPageRoute(builder: (_) => const LoginScreen()),
                            (route) => false,
                          );
                        }
                      },
                      child: child ?? const SizedBox.shrink(),
                    ),
                  ],
                ),
              ),
            ),
          );
        },

        // نقطة البداية الوحيدة — SplashScreen تتولى التوجيه
        home: const SplashScreen(),
      ),
    );
  }
}
