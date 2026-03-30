// File: lib/main.dart
//
// نقطة دخول التطبيق — نظيفة ومُخفَّفة.
// لا await لقراءة Storage هنا — هذا دور AuthBloc عبر SplashScreen.

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';

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

Future<void> main() async {
  // 1. ضمان تهيئة Flutter قبل أي async
  WidgetsFlutterBinding.ensureInitialized();

  // 2. تهيئة دعم التاريخ العربي (intl)
  await initializeDateFormatting('ar', null);

  // +++ تحميل متغيرات البيئة المخفية قبل أي اتصال بالشبكة +++
  await dotenv.load(fileName: ".env");

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

  // 4. تشغيل التطبيق — كل منطق التوثيق يعمل داخل AuthBloc
  runApp(const MyApp());
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
          visualDensity: VisualDensity.adaptivePlatformDensity,
          fontFamily: 'Cairo',
        ),

        // دعم اللغة العربية
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [Locale('ar', '')],
        locale: const Locale('ar', ''),

        // +++ المراقب العام (Global Listener) لحالة التوثيق +++
        builder: (context, child) {
          return BlocListener<AuthBloc, AuthState>(
            listener: (context, state) {
              if (state is AuthUnauthenticated) {
                // إذا العقل المدبر قرر طرد المستخدم، ننفذ الطرد من هنا بأمان
                navigatorKey.currentState?.pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const LoginScreen()),
                  (route) => false,
                );
              }
            },
            child: child ?? const SizedBox.shrink(),
          );
        },

        // نقطة البداية الوحيدة — SplashScreen تتولى التوجيه
        home: const SplashScreen(),
      ),
    );
  }
}
