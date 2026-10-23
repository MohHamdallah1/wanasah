import 'package:flutter/material.dart';
import 'dart:developer' as developer;
import '../services/location_service.dart';
import '../features/shops/presentation/shop_location_feedback.dart';
import '../features/shops/application/shop_creation_service.dart';
import '../features/shops/domain/shop_creation.dart'; // +++   استيراد خدمة الموقع المركزية المحصنة +++
import '../features/shops/presentation/shop_creation_failure_message.dart';

class AddShopScreen extends StatefulWidget {
  const AddShopScreen({super.key});

  @override
  State<AddShopScreen> createState() => _AddShopScreenState();
}

class _AddShopScreenState extends State<AddShopScreen> {
  final _formKey = GlobalKey<FormState>();
  final ShopCreationService _shopCreationService = ShopCreationService();
  ShopCreateCommand? _pendingShopCommand;

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
      // +++   الاعتماد على الخدمة المركزية المحصنة ضد الـ Fake GPS وتزوير الوقت +++
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
    } catch (error, stack) {
      final failure = error is LocationFailure ? error :
        LocationFailure(LocationFailureKind.unexpected,
          cause: error, causeStackTrace: stack);
      developer.log('AddShop location failure: ${failure.code}');
      if (mounted) {
        final errorMsg = shopLocationFailureMessage(failure.kind,
          languageCode: Localizations.localeOf(context).languageCode);

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
    if (!_formKey.currentState!.validate()) return;

    final locationText = _locationFieldController.text.trim();
    final isGpsValid = _currentLatitude != null &&
        _currentLongitude != null &&
        locationText.startsWith('Lat:');
    final isLinkValid = !isGpsValid && locationText.isNotEmpty;

    if (!isGpsValid && !isLinkValid) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('الرجاء تحديد الموقع عبر GPS أو إدخال رابط الموقع.'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    if (_isSaving) return;
    setState(() => _isSaving = true);

    final command = _pendingShopCommand ??= _shopCreationService.prepare(
      name: _nameController.text.trim(),
      phoneNumber: _phoneController.text.trim(),
      address: _governorateAreaController.text.trim(),
      contactPerson: _contactPersonController.text.trim(),
      notes: _notesController.text.trim(),
      locationLink: isLinkValid ? locationText : null,
      latitude: isGpsValid ? _currentLatitude : null,
      longitude: isGpsValid ? _currentLongitude : null,
    );

    try {
      final result = await _shopCreationService.execute(command);
      if (!mounted) return;

      _pendingShopCommand = null;
      final readiness = result.commercialReadiness;
      final message = readiness.saleReady
          ? 'تم حفظ المحل بنجاح.'
          : 'تم حفظ المحل، لكنه يحتاج إكمال الإعداد التجاري من الإدارة قبل البيع.';

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(message),
          backgroundColor: readiness.saleReady ? Colors.green : Colors.orange,
        ),
      );
      Navigator.pop(context, true);
    } on ShopCreateFailure catch (failure) {
      if (!mounted) return;
      if (!failure.ambiguous) {
        _pendingShopCommand = null;
      }
      final message = shopCreationFailureMessage(
        failure,
        languageCode: Localizations.localeOf(context).languageCode,
      );
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message), backgroundColor: Colors.red),
      );
    } catch (e) {
      developer.log('Unexpected shop creation failure: $e');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('حدث خطأ غير متوقع أثناء إضافة المحل.'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }
  // --- نهاية دالة حفظ المحل ---

  @override
  Widget build(BuildContext context) {
    // Scaffold لا يمكن أن تكون const بسبب الـ body والـ AppBar
    return Scaffold(
      // +++  لظاهرة الأشباح: إغلاق الثقب البصري بلون صلب حتى اكتمال تصميم الواجهة الزجاجية +++
      backgroundColor: Colors.grey.shade50,
      appBar: AppBar(
        backgroundColor: Colors.grey.shade50,
        elevation: 0,
        title: const Text('إضافة محل جديد'), // النص ثابت، يمكن إضافة const
        centerTitle: true,
      ),
      // SingleChildScrollView يمكن أن تكون const إذا كان الـ child والـ padding هما const
      // لكن الـ child (Form) ليس const بسبب المفتاح key
      body: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
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
    );
  }
}
