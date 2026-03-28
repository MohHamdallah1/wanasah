import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'dart:developer' as developer;
import 'dart:async'; // لاستخدام TimeoutException
import 'package:geolocator/geolocator.dart'; // لاستخدام geolocator
import '../services/auth_utils.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AddShopScreen extends StatefulWidget {
  const AddShopScreen({super.key});

  @override
  State<AddShopScreen> createState() => _AddShopScreenState();
}

class _AddShopScreenState extends State<AddShopScreen> {
  final _formKey = GlobalKey<FormState>();

  // --- Controllers للحقول (تم تعديل الأسماء والوظائف) ---
  final _nameController = TextEditingController(); // اسم المحل (إجباري)
  final _contactPersonController =
      TextEditingController(); // اسم المسؤول (إجباري)
  final _governorateAreaController =
      TextEditingController(); // المحافظة/المنطقة (إجباري) - كان للرابط سابقاً
  final _locationFieldController =
      TextEditingController(); // الموقع (رابط أو زر) (إجباري) - كان للعنوان سابقاً
  final _phoneController = TextEditingController(); // الهاتف (إجباري)
  final _notesController = TextEditingController(); // الملاحظات (اختياري)

  // --- متغيرات الحالة ---
  bool _isSaving = false;
  bool _isGettingLocation = false;
  double? _currentLatitude;
  double? _currentLongitude;
  bool _isOnBreak = false; // +++ حالة الاستراحة

  @override
  void initState() {
    super.initState();
    _checkBreakStatus();
  }

  Future<void> _checkBreakStatus() async {
    final breakStr = await const FlutterSecureStorage().read(
      key: 'is_on_break',
    );
    if (mounted) {
      setState(() {
        _isOnBreak = breakStr == 'true';
      });
    }
  }

  @override
  void dispose() {
    // التخلص من جميع الـ Controllers
    _nameController.dispose();
    _contactPersonController.dispose();
    _governorateAreaController.dispose(); // اسم جديد
    _locationFieldController.dispose(); // اسم جديد
    _phoneController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  // --- دالة جلب الموقع الجغرافي (لا تغيير هنا) ---
  Future<void> _getCurrentLocation() async {
    if (_isGettingLocation) return;
    setState(() {
      _isGettingLocation = true;
      _currentLatitude = null;
      _currentLongitude = null;
    });
    developer.log('Starting location fetching process...');
    try {
      bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        developer.log('Location services are disabled.');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('الرجاء تفعيل خدمات الموقع (GPS) في جهازك.'),
              backgroundColor: Colors.red,
            ),
          );
        }
        throw Exception('Location services are disabled.');
      }
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        developer.log('Location permission denied, requesting permission...');
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          developer.log('Location permission denied after request.');
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'تم رفض إذن الوصول للموقع. لا يمكن تحديد الموقع.',
                ),
                backgroundColor: Colors.red,
              ),
            );
          }
          throw Exception('Location permission denied.');
        }
      }
      if (permission == LocationPermission.deniedForever) {
        developer.log('Location permission denied forever.');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'تم رفض إذن الوصول للموقع بشكل دائم. يرجى تفعيله من إعدادات التطبيق.',
              ),
              backgroundColor: Colors.red,
            ),
          );
        }
        throw Exception('Location permission denied forever.');
      }
      developer.log(
        'Location permissions granted, getting current position...',
      );
      Position currentPosition = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      ).timeout(const Duration(seconds: 5));
      if (mounted) {
        setState(() {
          _currentLatitude = currentPosition.latitude;
          _currentLongitude = currentPosition.longitude;
          _locationFieldController.text =
              'Lat: ${_currentLatitude?.toStringAsFixed(5)}, Lng: ${_currentLongitude?.toStringAsFixed(5)}';
        });
        developer.log(
          'Location fetched: Lat: $_currentLatitude, Lng: $_currentLongitude',
        );
        // مسح حقل نص الموقع عند نجاح الالتقاط (اختياري - لتحسين التجربة)
        // _locationFieldController.clear();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'تم تحديد الموقع بنجاح! (Lat: ${_currentLatitude?.toStringAsFixed(5)}, Lng: ${_currentLongitude?.toStringAsFixed(5)})',
            ),
            backgroundColor: Colors.green,
          ),
        );
      }
    } catch (e) {
      developer.log('Error getting location: $e');
      if (mounted) {
        String errorMsg = 'حدث خطأ: ${e.toString()}';
        if (e is TimeoutException) {
          errorMsg =
              'فشل الاتصال بالسيرفر (Timeout). الرجاء التحقق من الشبكة أو حالة السيرفر.';
        } else if (e.toString().contains('Location services are disabled')) {
          errorMsg = 'الرجاء تفعيل خدمات الموقع (GPS) في جهازك.';
        } else if (e.toString().contains('Location permission denied')) {
          errorMsg = 'تم رفض إذن الوصول للموقع.';
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMsg), backgroundColor: Colors.red),
        );
      }
    } finally {
      developer.log('Location fetching process finished.');
      if (mounted) {
        setState(() {
          _isGettingLocation = false;
        });
      }
    }
  }

  // --- دالة حفظ المحل (تم تعديلها لتناسب الحقول الجديدة) ---
  Future<void> _saveShop() async {
    // 1. التحقق من صحة الفورم (سيتحقق فقط من اسم المحل والمسؤول الآن)
    if (!_formKey.currentState!.validate()) {
      return;
    }
    // +++ التعديل الجديد: التحقق الإجباري من الموقع الجغرافي +++
    if (_currentLatitude == null &&
        _currentLongitude == null &&
        _locationFieldController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('الرجاء تحديد الموقع عبر الـ GPS أو وضع رابط الموقع!'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }
    // +++++++++++++++++++++++++++++++++++++++++++++++++++++++

    if (_isSaving) return;
    setState(() {
      _isSaving = true;
    });

    try {
      final headers = await getAuthenticatedHeaders();
      const String baseUrl = 'http://10.0.2.2:5000';
      final url = Uri.parse('$baseUrl/shops');

      // --- تجهيز جسم الطلب (Request Body) ---
      Map<String, dynamic> requestBody = {
        'name': _nameController.text.trim(),
        'contact_person': _contactPersonController.text.trim(),
      };

      // إضافة الحقول إجباري النصية الأخرى إذا كانت غير فارغة
      if (_governorateAreaController.text.trim().isNotEmpty) {
        requestBody['address'] = _governorateAreaController.text.trim();
      }
      if (_phoneController.text.trim().isNotEmpty) {
        requestBody['phone_number'] = _phoneController.text.trim();
      }
      if (_notesController.text.trim().isNotEmpty) {
        requestBody['notes'] = _notesController.text.trim();
      }

      // إضافة الإحداثيات إذا تم التقاطها عبر الزر
      bool coordsCaptured = false; // متغير لتتبع إذا التقطنا إحداثيات
      if (_currentLatitude != null && _currentLongitude != null) {
        requestBody['latitude'] = _currentLatitude;
        requestBody['longitude'] = _currentLongitude;
        coordsCaptured = true; // تم التقاط الإحداثيات
        developer.log(
          'Adding coordinates to request body: Lat: $_currentLatitude, Lng: $_currentLongitude',
        );
      } else {
        developer.log('Coordinates not captured via button.');
      }

      // --- تعديل هنا: إضافة الرابط اليدوي فقط إذا لم يتم التقاط إحداثيات وكان الحقل غير فارغ ---
      if (!coordsCaptured && _locationFieldController.text.trim().isNotEmpty) {
        // فقط إذا لم نلتقط إحداثيات عبر الزر، نأخذ القيمة من الحقل النصي
        requestBody['location_link'] = _locationFieldController.text.trim();
        developer.log(
          'Adding manual location link from text field: ${requestBody['location_link']}',
        );
      } else if (_locationFieldController.text.trim().isNotEmpty) {
        // تم التقاط إحداثيات، ولكن الحقل النصي يحتوي قيمة (ربما بقايا "Lat: Lng:" أو رابط يدوي لم يتم مسحه)
        // سنتجاهل القيمة النصية ولن نرسلها كـ location_link لأن الإحداثيات لها الأولوية
        developer.log(
          'Coordinates were captured, ignoring text field content for location_link: ${_locationFieldController.text}',
        );
      }

      developer.log('Sending data to $url');
      developer.log('Request Body: ${jsonEncode(requestBody)}');

      // --- إرسال طلب POST ---
      final response = await http
          .post(url, headers: headers, body: jsonEncode(requestBody))
          .timeout(const Duration(seconds: 15));

      developer.log('Response Status Code: ${response.statusCode}');
      developer.log('Response Body: ${response.body}');

      // --- معالجة الرد ---
      if (!mounted) return;
      if (response.statusCode == 201) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('تم حفظ المحل بنجاح!'),
            backgroundColor: Colors.green,
          ),
        );
        Navigator.pop(context, true);
      } else if (response.statusCode == 401) {
        handleUnauthorized(context);
      } else {
        // ... (نفس كود معالجة الأخطاء الأخرى) ...
        String errorMessage = 'فشل حفظ المحل. الرجاء المحاولة مرة أخرى.';
        try {
          final responseBody = jsonDecode(response.body);
          if (responseBody is Map && responseBody.containsKey('message')) {
            errorMessage = 'فشل حفظ المحل: ${responseBody['message']}';
          }
        } catch (e) {
          developer.log('Could not parse error response body: $e');
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMessage), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      // ... (نفس كود معالجة الأخطاء العامة) ...
      developer.log('Error saving shop: $e');
      developer.log('Error Type: ${e.runtimeType}');
      if (mounted) {
        String errorMsg = 'حدث خطأ في الاتصال: ${e.toString()}';
        if (e is TimeoutException) {
          errorMsg =
              'فشل الاتصال بالسيرفر (Timeout). الرجاء التحقق من الشبكة أو حالة السيرفر.';
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMsg), backgroundColor: Colors.red),
        );
      }
    } finally {
      developer.log('Executing finally block...');
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }
  // --- نهاية دالة حفظ المحل ---

  @override
  Widget build(BuildContext context) {
    // Scaffold لا يمكن أن تكون const بسبب الـ body والـ AppBar
    return Scaffold(
      appBar: AppBar(
        title: const Text('إضافة محل جديد'), // النص ثابت، يمكن إضافة const
        centerTitle: true,
      ),
      // SingleChildScrollView يمكن أن تكون const إذا كان الـ child والـ padding هما const
      // لكن الـ child (Form) ليس const بسبب المفتاح key
      body: IgnorePointer(
        ignoring:
            _isOnBreak, // +++ شل حركة إضافة المحل بالكامل وقت الاستراحة +++
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0), // EdgeInsets.all ثابتة = const
          child: Form(
            key: _formKey, // وجود key يمنع Form من أن تكون const
            // Column ليست const لأن أبناءها (TextFormField) ليسوا const
            child: Column(
              crossAxisAlignment:
                  CrossAxisAlignment.stretch, // هذه الخاصية لا تقبل const عادة
              children: [
                // --- حقل اسم المحل (إجباري) ---
                TextFormField(
                  controller: _nameController,
                  // يمكن أن تكون const لأن كل خصائصها ثوابت
                  decoration: const InputDecoration(
                    labelText: 'اسم المحل *',
                    border: OutlineInputBorder(), // ثابتة = const
                    prefixIcon: Icon(
                      Icons.storefront_outlined,
                    ), // أيقونة ثابتة = const
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'الرجاء إدخال اسم المحل';
                    }
                    return null; // لا تنسَ إرجاع null في حالة النجاح
                  },
                ),
                const SizedBox(height: 16), // ثابتة = const
                // --- حقل اسم الشخص المسؤول (إجباري) ---
                TextFormField(
                  controller: _contactPersonController,
                  decoration: const InputDecoration(
                    labelText: 'اسم الشخص المسؤول *',
                    border: OutlineInputBorder(), // const
                    prefixIcon: Icon(Icons.person_outline), // const
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'الرجاء إدخال اسم الشخص المسؤول';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 16), // const
                // --- حقل المحافظة / المنطقة (إجباري) ---
                TextFormField(
                  controller: _governorateAreaController,
                  decoration: const InputDecoration(
                    labelText: 'المحافظة / المنطقة / خط السير *',
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.map_outlined),
                  ),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'الرجاء إدخال المنطقة أو خط السير';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 16), // const
                // --- حقل الموقع (رابط أو زر) (إجباري) ---
                TextFormField(
                  controller: _locationFieldController,
                  // لا يمكن أن تكون const بسبب suffixIcon المتغير
                  decoration: InputDecoration(
                    labelText: 'الموقع (رابط أو اضغط الزر)',
                    hintText: 'الصق رابط الموقع هنا أو استخدم الزر ->',
                    border: const OutlineInputBorder(), // const
                    prefixIcon: const Icon(Icons.link), // const
                    suffixIcon: IconButton(
                      // هذا الويدجت يعتمد على الحالة
                      icon:
                          _isGettingLocation
                              ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ) // الجزء داخل الشرط يمكن أن يكون const
                              : const Icon(
                                Icons.my_location,
                              ), // الجزء الآخر يمكن أن يكون const
                      tooltip: 'تحديد الموقع الحالي',
                      onPressed:
                          _isGettingLocation
                              ? null
                              : _getCurrentLocation, // يعتمد على الحالة
                    ),
                  ),
                  keyboardType: TextInputType.url,
                ),
                const SizedBox(height: 16), // const
                // --- حقل رقم الهاتف (إجباري) ---
                TextFormField(
                  controller: _phoneController,
                  decoration: const InputDecoration(
                    labelText: 'رقم الهاتف *',
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.phone_outlined),
                  ),
                  keyboardType: TextInputType.phone,
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'الرجاء إدخال رقم الهاتف';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 16), // const
                // --- حقل الملاحظات (اختياري) ---
                TextFormField(
                  controller: _notesController,
                  decoration: const InputDecoration(
                    labelText: 'ملاحظات إضافية',
                    border: OutlineInputBorder(), // const
                    prefixIcon: Icon(Icons.notes), // const
                  ),
                  maxLines: 3,
                ),
                const SizedBox(height: 32), // const
                // --- زر الحفظ ---
                // لا يمكن أن يكون const بسبب onPressed و icon المتغيرين
                ElevatedButton.icon(
                  onPressed: _isSaving ? null : _saveShop,
                  icon:
                      _isSaving
                          // الويدجتس داخل الشرط يمكن أن تكون const
                          ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              color: Colors.white,
                              strokeWidth: 2,
                            ),
                          )
                          : const Icon(Icons.save_alt_outlined),
                  label: const Text('حفظ المحل'), // النص ثابت = const
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                      vertical: 15,
                    ), // EdgeInsets ثابت = const
                    textStyle: const TextStyle(
                      fontSize: 16,
                    ), // TextStyle ثابت = const
                    // backgroundColor قد يعتمد على الـ Theme لذا لا نجعله const هنا
                  ),
                ),
                // --- نهاية زر الحفظ ---
              ],
            ),
          ),
        ),
      ),
    );
  }
}
