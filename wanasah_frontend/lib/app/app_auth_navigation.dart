import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_state.dart';
import '../screens/login_screen.dart';

class AppAuthNavigationListener extends StatelessWidget {
  const AppAuthNavigationListener({
    required this.authBloc,
    required this.navigatorKey,
    required this.child,
    super.key,
  });

  final AuthBloc authBloc;
  final GlobalKey<NavigatorState> navigatorKey;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return BlocListener<AuthBloc, AuthState>(
      bloc: authBloc,
      listener: (context, state) {
        if (state is! AuthUnauthenticated) return;

        bool isAlreadyOnLogin = false;
        navigatorKey.currentState?.popUntil((route) {
          if (route.settings.name == '/login') {
            isAlreadyOnLogin = true;
          }
          return true;
        });

        if (isAlreadyOnLogin) return;

        navigatorKey.currentState?.pushAndRemoveUntil(
          MaterialPageRoute(
            settings: const RouteSettings(name: '/login'),
            builder: (_) => const LoginScreen(),
          ),
          (route) => false,
        );
      },
      child: child,
    );
  }
}
