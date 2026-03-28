// File: lib/screens/splash_screen.dart
//
// الشاشة الأولى التي يراها التطبيق.
// مهمتها الوحيدة: إطلاق CheckAuthEvent والاستماع للنتيجة.
// لا تحتوي على أي منطق توثيق — هذا دور AuthBloc.

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import '../blocs/auth/auth_state.dart';
import 'dashboard_screen.dart';
import 'login_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    // إطلاق فحص التوثيق فور بناء الشاشة
    context.read<AuthBloc>().add(const CheckAuthEvent());
  }

  @override
  Widget build(BuildContext context) {
    return BlocListener<AuthBloc, AuthState>(
      listener: (context, state) {
        if (state is AuthAuthenticated) {
          // توجيه إلى لوحة التحكم وإزالة SplashScreen من الـ Stack
          Navigator.of(context).pushReplacement(
            MaterialPageRoute(
              builder: (_) => DashboardScreen(driverId: state.driverId),
            ),
          );
        } else if (state is AuthUnauthenticated || state is AuthError) {
          // توجيه إلى شاشة تسجيل الدخول وإزالة SplashScreen من الـ Stack
          Navigator.of(context).pushReplacement(
            MaterialPageRoute(builder: (_) => const LoginScreen()),
          );
        }
        // AuthLoading → لا إجراء، نبقى على شاشة التحميل
      },
      child: Scaffold(
        backgroundColor: Colors.teal.shade800,
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // ─── Logo / اسم التطبيق ───────────────────────────────────
              const Icon(
                Icons.directions_car_filled_rounded,
                size: 80,
                color: Colors.white,
              ),
              const SizedBox(height: 16),
              const Text(
                'وناسة',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 32,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 2,
                ),
              ),
              const SizedBox(height: 48),
              // ─── مؤشر التحميل ─────────────────────────────────────────
              const CircularProgressIndicator(
                color: Colors.white,
                strokeWidth: 3,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
