import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:http/http.dart' as http; // +++ استرجاع مكتبتك الموثوقة +++
import 'dart:convert';
import '../services/api_constants.dart'; // +++ لجلب رابط السيرفر الصحيح +++
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
  final _usernameController = TextEditingController(
    text: 'testdriver',
  ); // قيمة مبدئية للتسهيل
  final _passwordController = TextEditingController(
    text: 'password',
  ); // قيمة مبدئية للتسهيل
  String _message = ''; // لعرض رسائل الحالة أو الخطأ
  bool _isLoading = false; // لتتبع حالة التحميل وعرض المؤشر

  // --- دالة تسجيل الدخول (مستقرة ومضادة لخطأ الـ BuildContext) ---
  Future<void> _login() async {
    if (_isLoading) return;

    setState(() {
      _isLoading = true;
      _message = 'جاري التحقق من البيانات...';
    });

    try {
      // 1. استخدام طريقتك الموثوقة والمباشرة للاتصال
      final url = Uri.parse('${ApiConstants.baseUrl}/login');
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'username': _usernameController.text.trim(),
              'password': _passwordController.text.trim(),
            }),
          )
          .timeout(const Duration(seconds: 15));

      // +++ الدرع المعماري: حماية الـ BuildContext من خطأ async gaps +++
      if (!mounted) return;

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['token'] != null && data['driver_id'] != null) {
          // هنا الـ context محمي تماماً ومسموح استخدامه
          context.read<AuthBloc>().add(
            LoginEvent(token: data['token'], driverId: data['driver_id']),
          );
        } else {
          setState(() => _message = 'خطأ: بيانات السيرفر غير مكتملة.');
        }
      } else if (response.statusCode == 401 || response.statusCode == 403) {
        setState(() => _message = 'اسم المستخدم أو كلمة المرور غير صحيحة');
      } else {
        setState(() => _message = 'فشل الاتصال (${response.statusCode})');
      }
    } catch (e) {
      if (mounted) {
        setState(() => _message = 'تأكد من اتصالك بالإنترنت وحالة السيرفر.');
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // +++ تغليف الشاشة بمستمع (Listener) لحالة التوثيق مع الحفاظ على تصميمك +++
    return BlocListener<AuthBloc, AuthState>(
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
      child: GestureDetector(
        onTap: () => FocusScope.of(context).unfocus(),
        child: Scaffold(
          appBar: AppBar(
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
                            _isLoading
                                ? null
                                : _login, // تعطيل الزر أثناء التحميل
                        style: ElevatedButton.styleFrom(
                          textStyle: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                          ), // حجم ووزن الخط
                          shape: RoundedRectangleBorder(
                            // حواف دائرية للزر
                            borderRadius: BorderRadius.circular(12.0),
                          ),
                          elevation: 5, // إضافة ظل بسيط
                        ),
                        child:
                            _isLoading
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
                    // عرض رسالة الحالة أو الخطأ
                    if (_message.isNotEmpty)
                      Text(
                        _message,
                        style: TextStyle(
                          color:
                              _message.contains('فشل') ||
                                      _message.contains('خطأ')
                                  ? Colors
                                      .redAccent[700] // لون أحمر أقوى للأخطاء
                                  : Colors.grey[700],
                          fontWeight: FontWeight.w500,
                        ),
                        textAlign: TextAlign.center,
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
