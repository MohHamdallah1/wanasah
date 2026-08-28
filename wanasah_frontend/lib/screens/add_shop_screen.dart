import 'package:flutter/material.dart';
import 'dart:developer' as developer;
import 'dart:async'; // لاستخدام TimeoutException
import '../core/network/api_client.dart'; // +++ الملحق المعماري للاتصالات +++
import 'package:dio/dio.dart'; // +++ لمعالجة أخطاء الشبكة بذكاء +++
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../services/location_service.dart'; // +++ الكي الجراحي: استيراد خدمة الموقع المركزية المحصنة +++

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
  // --- دالة جلب الموقع الجغرافي (النسخة المعمارية المحصنة) ---
  Future<void> _getCurrentLocation() async {
    if (_isGettingLocation) return;
    setState(() {
      _isGettingLocation = true;
      _currentLatitude = null;
      _currentLongitude = null;
    });
    
    developer.log('Starting location fetching via LocationService...');
    
    try {
      // +++ الكي الجراحي: الاعتماد على الخدمة المركزية المحصنة ضد الـ Fake GPS وتزوير الوقت +++
      final position = await LocationService.instance.getCurrentLocation();
      
      if (mounted) {
        setState(() {
          _currentLatitude = position?.latitude;
          _currentLongitude = position?.longitude;
          _locationFieldController.text = 'Lat: ${_currentLatitude?.toStringAsFixed(5)}, Lng: ${_currentLongitude?.toStringAsFixed(5)}';
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('تم تحديد الموقع بنجاح!'), backgroundColor: Colors.green),
        );
      }
    } catch (e) {
      developer.log('Error getting location in AddShop: $e');
      if (mounted) {
        String errorMsg = 'حدث خطأ غير متوقع في تحديد الموقع.';
        final errStr = e.toString();
        
        // ترجمة رموز الأخطاء القادمة من LocationService
        if (errStr.contains('GPS_DISABLED')) {
          errorMsg = 'الرجاء تفعيل خدمات الموقع (GPS) في جهازك.';
        } else if (errStr.contains('GPS_DENIED_FOREVER')) {
          errorMsg = 'صلاحية الموقع مرفوضة نهائياً. يرجى تفعيلها من إعدادات التطبيق.';
        } else if (errStr.contains('GPS_DENIED')) {
          errorMsg = 'تم رفض إذن الوصول للموقع.';
        } else if (errStr.contains('GPS_TIMEOUT')) {
          errorMsg = 'فشل الاتصال بالـ GPS (Timeout). حاول في مكان مفتوح.';
        } else if (errStr.contains('FAKE_GPS_DETECTED')) {
          errorMsg = 'تحذير أمني: يرجى إيقاف تطبيقات تزوير الموقع (Fake GPS).';
        }

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMsg), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isGettingLocation = false);
      }
    }
  }

  // --- دالة حفظ المحل (تم تعديلها لتناسب الحقول الجديدة ومعمارية ApiClient) ---
  Future<void> _saveShop() async {
    // 1. التحقق من صحة الفورم
    if (!_formKey.currentState!.validate()) {
      return;
    }

    final String locationText = _locationFieldController.text.trim();
    // 1. تقييم الشروط أولاً بناءً على نية المندوب الحقيقية (الموجود في الشاشة)
    final bool isGpsValid = _currentLatitude != null && _currentLongitude != null && locationText.startsWith('Lat:');
    final bool isLinkValid = !isGpsValid && locationText.isNotEmpty;

    // +++ الكي الجراحي (SHP-2): التحقق الموحد لمنع ثغرة الـ Ghost GPS تماماً +++
    if (!isGpsValid && !isLinkValid) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('الرجاء تحديد الموقع عبر الـ GPS أو وضع رابط صحيح للموقع!'), backgroundColor: Colors.red),
      );
      return;
    }

    if (_isSaving) return;
    setState(() => _isSaving = true);

    try {
      Map<String, dynamic> requestBody = {
        'name': _nameController.text.trim(),
        'contact_person': _contactPersonController.text.trim(),
      };

      if (_governorateAreaController.text.trim().isNotEmpty) requestBody['address'] = _governorateAreaController.text.trim();
      if (_phoneController.text.trim().isNotEmpty) requestBody['phone_number'] = _phoneController.text.trim();
      if (_notesController.text.trim().isNotEmpty) requestBody['notes'] = _notesController.text.trim();

      // إرفاق الموقع بناءً على الشرط الذي نجح
      if (isGpsValid) {
        requestBody['latitude'] = _currentLatitude;
        requestBody['longitude'] = _currentLongitude;
      } else if (isLinkValid) {
        requestBody['location_link'] = locationText;
      }

      developer.log('Request Body: $requestBody');

      // --- إرسال طلب POST باستخدام ApiClient المعماري ---
      final response = await ApiClient.instance.post(
        '/shops', // +++ المسار الحقيقي من routes.py +++
        data: requestBody,
      );

      if (!mounted) return;

      // +++ الكي الجراحي: حماية الشاشة من التجميد في حال تغير كود النجاح من الباك إند +++
      if (response.statusCode == 201 || response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('تم حفظ المحل بنجاح!'),
            backgroundColor: Colors.green,
          ),
        );
        Navigator.pop(context, true);
      }
    } on DioException catch (e) {
      developer.log('DioException saving shop: ${e.message}');
      if (!mounted) return;

      String errorMessage = 'فشل حفظ المحل. الرجاء المحاولة مرة أخرى.';
      if (e.response?.data != null && e.response?.data is Map) {
        // +++ الدرع النخبوي (Elite Shield) لالتقاط أخطاء FastAPI و Pydantic بصيغتها المعقدة ومنع الـ Type Crash +++
        final Map<dynamic, dynamic> errorData = e.response!.data as Map;
        
        if (errorData['message'] != null && errorData['message'] is String) {
          errorMessage = 'فشل الحفظ: ${errorData['message']}';
        } else if (errorData['detail'] != null) {
          final dynamic detail = errorData['detail'];
          if (detail is List && detail.isNotEmpty) {
            // التقاط خطأ التحقق (Validation Error) من Pydantic
            final firstError = detail[0] as Map;
            errorMessage = 'خطأ في البيانات: ${firstError['msg']}';
          } else if (detail is String) {
            errorMessage = 'فشل الحفظ: $detail';
          }
        }
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(errorMessage), backgroundColor: Colors.red),
      );
    } catch (e) {
      developer.log('Error saving shop: $e');
      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('حدث خطأ في الاتصال: ${e.toString()}'),
          backgroundColor: Colors.red,
        ),
      );
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
      // +++ النسف المعماري لظاهرة الأشباح: إغلاق الثقب البصري بلون صلب حتى اكتمال تصميم الواجهة الزجاجية +++
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        backgroundColor: Colors.grey.shade50,
        elevation: 0,
        title: const Text('إضافة محل جديد'), // النص ثابت، يمكن إضافة const
        centerTitle: true,
      ),
      // SingleChildScrollView يمكن أن تكون const إذا كان الـ child والـ padding هما const
      // لكن الـ child (Form) ليس const بسبب المفتاح key
      body: IgnorePointer(
        ignoring: _isOnBreak, 
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // +++ SHP-1: لافتة تحذيرية واضحة للمندوب بدلاً من الشلل الصامت +++
                if (_isOnBreak)
                  Container(
                    margin: const EdgeInsets.only(bottom: 16),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.orange.shade100,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.orange.shade300),
                    ),
                    child: const Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: Colors.orange),
                        SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'أنت في وقت الاستراحة. لا يمكنك إضافة محلات جديدة الآن.',
                            style: TextStyle(color: Colors.deepOrange, fontWeight: FontWeight.bold),
                          ),
                        ),
                      ],
                    ),
                  ),
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
                    // +++ درع Regex: التأكد من أن الإدخال رقم هاتف صالح (7 إلى 15 رقم) +++
                    if (!RegExp(r'^\+?[0-9]{7,15}$').hasMatch(value.trim())) {
                      return 'رقم الهاتف غير صالح';
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
