// File: lib/main.dart

import 'dart:ui' as ui;
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import 'blocs/auth/auth_bloc.dart';
import 'core/network/api_client.dart';
import 'screens/splash_screen.dart';
import 'screens/login_screen.dart';
import 'blocs/dashboard/dashboard_bloc.dart';
import 'blocs/auth/auth_event.dart';
import 'blocs/auth/auth_state.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

// إصلاح 1: إنشاء نسخة عالمية من AuthBloc لتجنب الاعتماد على context قد يكون فارغاً
final AuthBloc globalAuthBloc = AuthBloc(); 

void _onPlatformError(Object error, StackTrace stack) {
  debugPrint('═══════════════ PLATFORM ASYNC CRASH ═══════════════');
  debugPrint('ERROR: $error');
  debugPrint('STACK: $stack');
  debugPrint('═══════════════════════════════════════════════════');
  Sentry.captureException(error, stackTrace: stack);
}

void _onFlutterError(FlutterErrorDetails details) {
  debugPrint('═══════════════ FLUTTER FRAMEWORK CRASH ═══════════════');
  debugPrint('EXCEPTION: ${details.exception}');
  debugPrint('STACK: ${details.stack}');
  if (details.library != null) {
    debugPrint('LIBRARY: ${details.library}');
  }
  debugPrint('════════════════════════════════════════════════════════');
  Sentry.captureException(details.exception, stackTrace: details.stack);
  if (kDebugMode) {
    FlutterError.presentError(details);
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // شاشة خطأ مخصصة في حال الانهيار لتجنب الشاشة البيضاء (White Screen of Death)
  ErrorWidget.builder = (FlutterErrorDetails details) {
    return const MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        body: Center(
          child: Text(
            'حدث خطأ حرج في النظام.\nيرجى التواصل مع الدعم الفني.',
            textAlign: TextAlign.center,
            textDirection: TextDirection.rtl,
          ),
        ),
      ),
    );
  };
  FlutterError.onError = _onFlutterError;
  ui.PlatformDispatcher.instance.onError = (error, stack) {
    _onPlatformError(error, stack);
    return true; 
  };

  await initializeDateFormatting('ar', null);

  // إصلاح M-2: منع ابتلاع غياب ملف البيئة في بيئة الإنتاج
  try {
    await dotenv.load(fileName: ".env");
  } catch (e) {
    if (kReleaseMode) {
      throw Exception('CRITICAL ERROR: .env file is missing in Release mode! Application cannot start safely.');
    } else {
      debugPrint('⚠️ تنبيه: ملف .env غير موجود. سيتم استخدام الروابط الافتراضية للتطوير.');
    }
  }

  ApiClient.init(
    onUnauthorized: () {
      globalAuthBloc.add(const LogoutEvent());
    },
  );

  // إصلاح M-3: تنبيه صريح إذا كان Sentry غير مفعل
  final sentryDsn = dotenv.env['SENTRY_DSN'] ?? '';
  if (sentryDsn.isEmpty) {
    debugPrint('⚠️ WARNING: SENTRY_DSN is empty. Sentry crash tracking is DISABLED.');
  }

  await SentryFlutter.init(
    (options) {
      options.dsn = sentryDsn;
      options.tracesSampleRate = 0.1;
    },
    appRunner: () => runApp(const MyApp()),
  );
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiBlocProvider(
      providers: [
        // توفير النسخة العالمية لبقية شاشات التطبيق
        BlocProvider<AuthBloc>.value(value: globalAuthBloc),
        BlocProvider<DashboardBloc>(create: (_) => DashboardBloc()),
      ],
      child: MaterialApp(
        title: 'Wanasah App',
        navigatorKey: navigatorKey,
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          primarySwatch: Colors.teal,
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
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [Locale('ar', '')],
        locale: const Locale('ar', ''),

        builder: (context, child) {
          return AnnotatedRegion<SystemUiOverlayStyle>(
            value: const SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              statusBarIconBrightness: Brightness.dark,
              systemNavigationBarColor: Colors.white, 
              systemNavigationBarIconBrightness: Brightness.dark,
              systemNavigationBarDividerColor: Colors.transparent,
            ),
            child: SafeArea(
              top: false,
              bottom: true, 
              child: Material(
                color: Colors.white,
                child: Stack(
                  children: [
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
                    BlocListener<AuthBloc, AuthState>(
                      bloc: globalAuthBloc, // الاستماع للنسخة العالمية
                      listener: (context, state) {
                        if (state is AuthUnauthenticated) {
                          // إصلاح 2: التحقق من المسار الحالي لمنع تضارب التوجيه مع SplashScreen
                          bool isAlreadyOnLogin = false;
                          navigatorKey.currentState?.popUntil((route) {
                            if (route.settings.name == '/login') {
                              isAlreadyOnLogin = true;
                            }
                            return true; 
                          });

                          if (!isAlreadyOnLogin) {
                            navigatorKey.currentState?.pushAndRemoveUntil(
                              MaterialPageRoute(
                                settings: const RouteSettings(name: '/login'),
                                builder: (_) => const LoginScreen(),
                              ),
                              (route) => false,
                            );
                          }
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
        home: const SplashScreen(),
      ),
    );
  }
}