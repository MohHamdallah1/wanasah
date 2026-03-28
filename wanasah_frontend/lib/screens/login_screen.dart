import 'package:flutter/material.dart';
import 'dart:developer' as developer;
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'dashboard_screen.dart'; // <-- تأكد من المسار الصحيح لهذه الشاشة
// +++ استيراد ضروري للحفظ الآمن +++
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
// +++++++++++++++++++++++++++++++++++

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _usernameController = TextEditingController(text: 'testdriver'); // قيمة مبدئية للتسهيل
  final _passwordController = TextEditingController(text: 'password'); // قيمة مبدئية للتسهيل
  String _message = ''; // لعرض رسائل الحالة أو الخطأ
  bool _isLoading = false; // لتتبع حالة التحميل وعرض المؤشر

  // +++ إضافة كائن التخزين الآمن +++
  final _secureStorage = const FlutterSecureStorage();


// --- دالة تسجيل الدخول (معدلة ومبسطة) ---
  Future<void> _login() async {
    if (_isLoading) return;

    setState(() {
      _isLoading = true;
      _message = 'جاري تسجيل الدخول...';
    });

    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();

    if (username.isEmpty || password.isEmpty) {
      setState(() {
        _message = 'الرجاء إدخال اسم المستخدم وكلمة المرور.';
        _isLoading = false;
      });
      return;
    }

    final url = Uri.parse('http://10.0.2.2:5000/login'); // تأكد من Base URL
    developer.log('Attempting login for $username to $url');

    try {
      final response = await http.post(
        url,
        headers: {'Content-Type': 'application/json; charset=UTF-8'},
        body: jsonEncode({'username': username, 'password': password}),
      ).timeout(const Duration(seconds: 15));

      if (!mounted) return;

      developer.log('>>> Login Response Status Code: ${response.statusCode}');
      developer.log('>>> Login Response Body: ${response.body}');

      if (response.statusCode == 200) {
        developer.log('>>> Login SUCCESS block entered.');
        try {
          // --- فك التشفير مرة واحدة ---
          final dynamic decodedBody = jsonDecode(response.body);

          // --- التحقق من أن الرد هو Map ويحتوي المفاتيح المطلوبة ---
          if (decodedBody is Map &&
              decodedBody.containsKey('token') &&
              decodedBody.containsKey('driver_id') &&
              decodedBody.containsKey('driver_name')) {

            final loginResponse = decodedBody as Map<String, dynamic>;

            // --- استخلاص البيانات مع التحقق من النوع ---
            final String? token = loginResponse['token'] as String?; // استخدم String? للاحتياط
            final int? driverId = loginResponse['driver_id'] as int?; // استخدم int? للاحتياط
            final String? driverName = loginResponse['driver_name'] as String?; // استخدم String? للاحتياط

            // --- التحقق من أن القيم ليست null أو فارغة قبل المتابعة ---
            if (token != null && token.isNotEmpty && driverId != null && driverName != null && driverName.isNotEmpty) { // <--- إضافة التحقق من driverName
              developer.log('Token, driverId, and driverName successfully extracted.');

              // --- محاولة الحفظ والانتقال ---
              try {
                await _secureStorage.write(key: 'auth_token', value: token);
                developer.log('Token saved successfully!');
                await _secureStorage.write(key: 'driver_id', value: driverId.toString());
                developer.log('Driver ID $driverId saved successfully!');
                 // قد تحتاج أيضاً لحفظ اسم السائق إذا كنت تريد عرضه لاحقاً
                // await _secureStorage.write(key: 'driver_name', value: driverName);
                // developer.log('Driver Name $driverName saved successfully!');

                // الانتقال للوحة التحكم بعد الحفظ الناجح
                if (mounted) {
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(
                      builder: (context) => DashboardScreen(driverId: driverId /*, driverName: driverName*/), // تمرير ID للسائق
                    ),
                  );
                  return; // الخروج من الدالة بعد الانتقال الناجح
                }
              } catch (storageError) { // خطأ أثناء الحفظ في Secure Storage
                developer.log('Error saving token or driverId: $storageError');
                if (mounted) {
                  setState(() {
                    _message = 'خطأ في حفظ بيانات الدخول الآمنة.';
                    _isLoading = false;
                  });
                }
              }
              // --- نهاية محاولة الحفظ ---

            } else {
              // --- لم يتم العثور على التوكن أو معرف السائق أو الاسم في الرد ---
              developer.log('Token, driver_id, or driver_name missing or null/empty in login response.');
              if (mounted) {
                setState(() {
                  _message = 'خطأ من السيرفر: استجابة الدخول غير مكتملة.';
                  _isLoading = false;
                });
              }
            }
            // --- نهاية التحقق من القيم المستخلصة ---

          } else {
            // الرد ليس بالشكل المتوقع (JSON لكن لا يحتوي المفاتيح)
            developer.log('>>> ERROR: Login response body is valid JSON but missing required keys (token, driver_id, driver_name)! Body: $decodedBody');
             if (mounted) {
               setState(() {
                 _message = 'خطأ في بيانات الاستجابة من الخادم.';
                 _isLoading = false;
               });
             }
          }
        } catch (decodeError, stacktrace) { // خطأ أثناء فك تشفير JSON
          developer.log('>>> ERROR: Failed to decode successful login JSON response body: $decodeError', stackTrace: stacktrace);
          developer.log('Raw response body for decode error: ${response.body}');
           if (mounted) {
             setState(() {
               _message = 'حدث خطأ في فهم استجابة السيرفر.';
               _isLoading = false;
             });
           }
        }
        // --- نهاية معالجة حالة 200 ---

      } else if (response.statusCode == 401) {
        // فشل تسجيل الدخول (بيانات خاطئة)
        setState(() {
          _message = 'فشل الدخول: اسم المستخدم أو كلمة المرور خاطئة.';
          _isLoading = false;
        });
      } else {
        // أخطاء أخرى من السيرفر
        developer.log('Login failed with status: ${response.statusCode}, body: ${response.body}');
        setState(() {
          _message = 'حدث خطأ من السيرفر: ${response.statusCode}';
          _isLoading = false;
        });
      }
    } catch (error, stacktrace) { // أخطاء الاتصال بالشبكة أو المهلة الزمنية أو أي خطأ آخر
      developer.log('Login Error: ${error.toString()}', error: error, stackTrace: stacktrace);
      if (!mounted) return;
      setState(() {
        _message = 'حدث خطأ في الاتصال بالخادم. يرجى المحاولة مرة أخرى.';
        _isLoading = false;
      });
    } finally {
        // تأكد من إيقاف التحميل في finally إذا لم يتم الانتقال
        // هذا يحتاج لتعديل بسيط لأننا نخرج بـ return بعد الانتقال الناجح
        // يمكن إضافة if (!mounted) return; هنا أيضاً
        // ولكن الطريقة الحالية بإيقاف التحميل داخل كل مسار خطأ كافية
        // if (mounted && _isLoading) { // Check if still loading (i.e., navigation didn't happen)
        //   setState(() { _isLoading = false; });
        // }
    }
  }
  // --- نهاية دالة _login ---


  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // استخدام GestureDetector لإخفاء لوحة المفاتيح عند الضغط خارج الحقول
    return GestureDetector(
      onTap: () => FocusScope.of(context).unfocus(),
      child: Scaffold(
        appBar: AppBar(
          title: const Text('تسجيل الدخول'), // تعديل العنوان
          centerTitle: true,
        ),
        body: Padding(
          padding: const EdgeInsets.all(20.0),
          child: Center(
            child: SingleChildScrollView( // للسماح بالتمرير إذا كانت الشاشة صغيرة
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
                      prefixIcon: const Icon(Icons.person_outline), // تغيير الأيقونة
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12.0), // تعديل الحواف
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
                      prefixIcon: const Icon(Icons.lock_outline), // تغيير الأيقونة
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
                      onPressed: _isLoading ? null : _login, // تعطيل الزر أثناء التحميل
                      style: ElevatedButton.styleFrom(
                        textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold), // حجم ووزن الخط
                        shape: RoundedRectangleBorder( // حواف دائرية للزر
                           borderRadius: BorderRadius.circular(12.0),
                        ),
                        elevation: 5, // إضافة ظل بسيط
                      ),
                      child: _isLoading
                          ? const SizedBox( height: 24, width: 24, child: CircularProgressIndicator(strokeWidth: 3, color: Colors.white))
                          : const Text('تسجيل الدخول'),
                    ),
                  ),
                  const SizedBox(height: 20.0),
                  // عرض رسالة الحالة أو الخطأ
                  if (_message.isNotEmpty)
                    Text(
                      _message,
                      style: TextStyle(
                        color: _message.contains('فشل') || _message.contains('خطأ')
                            ? Colors.redAccent[700] // لون أحمر أقوى للأخطاء
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
    );
  }
}