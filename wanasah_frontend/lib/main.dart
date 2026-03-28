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

/// navigatorKey عالمي — مُشترَك بين MaterialApp وApiClient
/// حتى يتمكن AuthInterceptor من التنقل بدون BuildContext.
final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

Future<void> main() async {
  // 1. ضمان تهيئة Flutter قبل أي async
  WidgetsFlutterBinding.ensureInitialized();

  // 2. تهيئة دعم التاريخ العربي (intl)
  await initializeDateFormatting('ar', null);

  // 3. تهيئة Dio / ApiClient مع navigatorKey
  ApiClient.init(navigatorKey: navigatorKey);

  // 4. تشغيل التطبيق — كل منطق التوثيق يعمل داخل AuthBloc
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocProvider<AuthBloc>(
      // إنشاء AuthBloc وتوفيره لكل شجرة الـ Widget
      create: (_) => AuthBloc(),
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

        // نقطة البداية الوحيدة — SplashScreen تتولى التوجيه
        home: const SplashScreen(),
      ),
    );
  }
}