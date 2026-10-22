import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../blocs/auth/auth_bloc.dart';
import '../blocs/dashboard/dashboard_bloc.dart';
import '../screens/splash_screen.dart';
import 'app_auth_navigation.dart';
import 'theme/app_system_ui.dart';
import 'theme/app_theme.dart';

final GlobalKey<NavigatorState> navigatorKey =
    GlobalKey<NavigatorState>();

final AuthBloc globalAuthBloc = AuthBloc();

class MyApp extends StatelessWidget {
  const MyApp({
    this.authBloc,
    super.key,
  });

  final AuthBloc? authBloc;

  @override
  Widget build(BuildContext context) {
    final resolvedAuthBloc = authBloc ?? globalAuthBloc;

    return MultiBlocProvider(
      providers: [
        BlocProvider<AuthBloc>.value(
          value: resolvedAuthBloc,
        ),
        BlocProvider<DashboardBloc>(
          create: (_) => DashboardBloc(),
        ),
      ],
      child: MaterialApp(
        title: 'Wanasah App',
        navigatorKey: navigatorKey,
        debugShowCheckedModeBanner: false,
        theme: AppTheme.data,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: const [
          Locale('ar', ''),
        ],
        locale: const Locale('ar', ''),
        builder: (context, child) {
          return AppSystemUi(
            child: AppAuthNavigationListener(
              authBloc: resolvedAuthBloc,
              navigatorKey: navigatorKey,
              child: child ?? const SizedBox.shrink(),
            ),
          );
        },
        home: const SplashScreen(),
      ),
    );
  }
}
