import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
// --- تم إعدام مكتبة http و api_constants بشكل نهائي من هنا ---
import '../blocs/auth/auth_bloc.dart';
import '../blocs/auth/auth_event.dart';
import '../blocs/auth/auth_state.dart';
import 'dashboard_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _usernameController = TextEditingController(text: 'testdriver');
  final _passwordController = TextEditingController(text: 'password');

  // --- دالة تسجيل الدخول (شاشة غبية ترسل الأوامر فقط) ---
  void _login() {
    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();

    if (username.isEmpty || password.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('الرجاء إدخال اسم المستخدم وكلمة المرور'),
          backgroundColor: Colors.orange,
        ),
      );
      return;
    }

    // إغلاق الكيبورد
    FocusScope.of(context).unfocus();

    // إرسال أمر تسجيل الدخول للعقل المدبر ليتولى هو كل شيء
    context.read<AuthBloc>().add(
      LoginRequested(username: username, password: password),
    );
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // +++ استخدام BlocConsumer للتحكم في الواجهة (builder) والاستماع للأحداث (listener) +++
    return BlocConsumer<AuthBloc, AuthState>(
      listener: (context, state) {
        if (state is AuthAuthenticated) {
          // بمجرد أن يعطي العقل إشارة النجاح، ننتقل للوحة القيادة
          Navigator.of(context).pushReplacement(
            MaterialPageRoute(
              builder: (_) => DashboardScreen(driverId: state.driverId),
            ),
          );
        } else if (state is AuthError) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(state.message), backgroundColor: Colors.red),
          );
        }
      },
      builder: (context, state) {
        // متغير للتحكم في الواجهة بناءً على حالة العقل المدبر
        final bool isLoading = state is AuthLoading;

        return GestureDetector(
          onTap: () => FocusScope.of(context).unfocus(),
          child: Scaffold(
            backgroundColor:
                Colors
                    .transparent, // +++ جعل الخلفية شفافة لرؤية التدرج العالمي +++
            appBar: AppBar(
              backgroundColor: Colors.transparent,
              elevation: 0,
              title: const Text('تسجيل الدخول'), // تعديل العنوان
              centerTitle: true,
            ),
            body: Padding(
              padding: const EdgeInsets.all(20.0),
              child: Center(
                child: SingleChildScrollView(
                  // للسماح بالتمرير إذا كانت الشاشة صغيرة
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: <Widget>[
                      // يمكنك إضافة شعار هنا إذا أردت
                      // Image.asset('assets/logo.png', height: 100),
                      // const SizedBox(height: 40.0),
                      TextField(
                        controller: _usernameController,
                        decoration: InputDecoration(
                          labelText: 'اسم المستخدم',
                          prefixIcon: const Icon(
                            Icons.person_outline,
                          ), // تغيير الأيقونة
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(
                              12.0,
                            ), // تعديل الحواف
                          ),
                          filled: true, // إضافة خلفية للحقل
                          fillColor: Colors.grey[100],
                        ),
                        keyboardType: TextInputType.text,
                      ),
                      const SizedBox(height: 16.0),
                      TextField(
                        controller: _passwordController,
                        decoration: InputDecoration(
                          labelText: 'كلمة المرور',
                          prefixIcon: const Icon(
                            Icons.lock_outline,
                          ), // تغيير الأيقونة
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12.0),
                          ),
                          filled: true,
                          fillColor: Colors.grey[100],
                        ),
                        obscureText: true, // لإخفاء كلمة المرور
                      ),
                      const SizedBox(height: 32.0),
                      // استخدام SizedBox لتحديد ارتفاع الزر بشكل أفضل
                      SizedBox(
                        height: 50, // تحديد ارتفاع الزر
                        child: ElevatedButton(
                          onPressed:
                              isLoading
                                  ? null
                                  : _login, // تعطيل الزر يتم برمجياً من حالة الـ Bloc
                          style: ElevatedButton.styleFrom(
                            textStyle: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12.0),
                            ),
                            elevation: 5,
                          ),
                          child:
                              isLoading
                                  ? const SizedBox(
                                    height: 24,
                                    width: 24,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 3,
                                      color: Colors.white,
                                    ),
                                  )
                                  : const Text('تسجيل الدخول'),
                        ),
                      ),
                      const SizedBox(height: 20.0),
                      // تم إزالة المتغير القديم _message والاعتماد كلياً على الـ SnackBar من الـ Bloc
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      }, // نهاية الـ builder الخاص بـ BlocConsumer
    ); // نهاية BlocConsumer
  }
}
