// --- الاستيرادات الأساسية ---
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'dart:developer' as developer;
import 'dart:async'; // لاستخدام TimeoutException و Future
import 'package:map_launcher/map_launcher.dart'; // لاستخدام MapLauncher و Coords
import 'package:url_launcher/url_launcher.dart'; // لفتح الروابط اليدوية
import 'dart:io'; // <-- أضف هذا السطر
// --- استيرادات التوثيق وشاشة الدخول (استخدم اسم مشروعك) ---
import 'package:wanasah_frontend/services/auth_utils.dart'; // <-- تأكد من المسار

// --- تعريف الكلاس StatefulWidget (بدون معلمات الموقع) ---
class VisitScreen extends StatefulWidget {
  final int visitId;
  final String shopName; // اسم المحل لا يزال يمرر لسهولة العرض في AppBar
  final double shopBalance;
  final String visitStatus; // يمكن استخدامها لتحديد الحالة الأولية للـ Outcome

  const VisitScreen({
    required this.visitId,
    required this.shopName,
    required this.shopBalance,
    required this.visitStatus, // يمكن إزالتها إذا لم تعد تستخدمها
    super.key
  });

  @override
  State<VisitScreen> createState() => _VisitScreenState();
}

// --- تعريف الكلاس State ---
class _VisitScreenState extends State<VisitScreen> {

  final _formKey = GlobalKey<FormState>();

  // --- متغيرات الحالة للحقول ---
  String? _selectedOutcome;
  final _quantityController = TextEditingController();
  final _cashController = TextEditingController();
  final _debtPaidController = TextEditingController();
  final _notesController = TextEditingController();

  // --- متغيرات الحالة العامة والتحميل ---
  bool _isSubmitting = false;
  List<Map<String, dynamic>> _productVariants = [];
  bool _isFetchingProducts = true;
  String? _fetchProductsError;
  int? _selectedProductVariantId;
  double? _expectedSaleValue;
  bool _isLoading = true; // للتحكم في مؤشر التحميل العام للشاشة
  String? _error; // لعرض الأخطاء العامة أثناء التحميل الأولي

  // +++ متغيرات حالة جديدة لبيانات الموقع المحملة +++
  double? _shopLatitude;
  double? _shopLongitude;
  String? _shopLink;
  String? _shopAddr; // العنوان النصي المحمل
  // ++++++++++++++++++++++++++++++++++++++++++++++++

  // --- دالة مساعدة لإيجاد ID المنتج الافتراضي بمرونة ---
  int? _findDefaultProductId() {
     if (_productVariants.isNotEmpty) {
         return _productVariants.first['id'] as int?;
     }
     return null;
  }


  // --- دوال دورة حياة الويدجت ---
  @override
  void initState() {
    super.initState();
    _fetchDataOnInit();
    _quantityController.addListener(_updateCalculatedInfo);
  }

  @override
  void dispose() {
    _quantityController.removeListener(_updateCalculatedInfo);
    _quantityController.dispose();
    _cashController.dispose();
    _debtPaidController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  // --- دالة تنظيم جلب البيانات ---
  Future<void> _fetchDataOnInit() async {
     if (!mounted) return;
     // بدء التحميل الكلي للشاشة (نعيد تعيين الأخطاء)
     // نضعها هنا لضمان ظهور المؤشر عند إعادة المحاولة
     setState(() { _isLoading = true; _error = null; _fetchProductsError = null; });

     try {
        developer.log("Starting initial data fetch...");
        // أولاً: جلب قائمة المنتجات
        await _fetchProductVariants();

        // ثانياً: جلب تفاصيل الزيارة (إذا نجحت المنتجات)
        if (mounted && _fetchProductsError == null) {
          developer.log("Product fetch successful, proceeding to load visit details...");
          await _loadVisitDetails();
        } else if(mounted && _fetchProductsError != null) {
           developer.log("Product fetch failed, setting screen error.");
           setState(() { _error = _fetchProductsError; });
        }

     } catch (e, s) {
        developer.log("Unexpected error during initial data fetch.", error: e, stackTrace: s);
        if (mounted) {
           setState(() { _error = 'خطأ غير متوقع أثناء تحميل بيانات الشاشة'; });
        }
     } finally {
        // إيقاف التحميل الكلي
        if (mounted) {
           developer.log("Finished initial data fetch. Setting isLoading to false.");
           setState(() { _isLoading = false; });
        }
     }
  }

  // --- دالة جلب المنتجات ---
  Future<void> _fetchProductVariants() async {
    if (!mounted) return;
    setState(() { _isFetchingProducts = true; _fetchProductsError = null; });

    final url = Uri.parse('http://10.0.2.2:5000/product_variants');
    developer.log('Fetching product variants from: $url');

    try {
       final headers = await getAuthenticatedHeaders(needsContentType: false);
       final response = await http.get(url, headers: headers).timeout(const Duration(seconds: 15));
       if (!mounted) return;

       if (response.statusCode == 401) {
          await handleUnauthorized(context);
          if (mounted) setState(() { _fetchProductsError = 'الجلسة غير صالحة'; _isFetchingProducts = false; });
          return;
       }

       if (response.statusCode == 200) {
          final List<dynamic> decodedData = jsonDecode(response.body);
          final List<Map<String, dynamic>> variantsList = List<Map<String, dynamic>>.from( decodedData.whereType<Map<String, dynamic>>() );

          setState(() {
             _productVariants = variantsList;
             _isFetchingProducts = false;
             _fetchProductsError = null;
             // لا نحدد الافتراضي هنا، نتركه لـ _loadVisitDetails أو للقيمة الأولية
          });
       } else {
          developer.log('Failed to load product variants. Status: ${response.statusCode}');
          if (mounted) { setState(() { _fetchProductsError = 'فشل تحميل قائمة المنتجات (${response.statusCode})'; _isFetchingProducts = false; }); }
       }
    } catch (error, stacktrace) {
       developer.log('Error fetching product variants: ${error.toString()}', error: error, stackTrace: stacktrace);
       if (!mounted) return;
       setState(() { _fetchProductsError = 'خطأ في الاتصال عند تحميل المنتجات'; _isFetchingProducts = false; });
    }
  }

 // --- دالة جلب تفاصيل الزيارة الحالية (معدلة لتخزين بيانات الموقع) ---
 Future<void> _loadVisitDetails() async {
    if (!mounted) return;

    final url = Uri.parse('http://10.0.2.2:5000/visits/${widget.visitId}'); // <-- تأكد من الـ Base URL
    developer.log('Fetching visit details from: $url');

    try {
       final headers = await getAuthenticatedHeaders(needsContentType: false);
       final response = await http.get(url, headers: headers).timeout(const Duration(seconds: 15));
       if (!mounted) return;

       if (response.statusCode == 401) {
          await handleUnauthorized(context);
          if (mounted) setState(() { _error = 'الجلسة غير صالحة'; });
          return;
       }

       if (response.statusCode == 200) {
          final visitData = jsonDecode(response.body);
          developer.log('Visit details received: $visitData');

          // --- تحديث الحالة بالبيانات المستلمة لتعبئة الحقول ---
          setState(() {
  _selectedOutcome = visitData['outcome'];

  // --- تعديل هنا: تعيين نص فارغ '' إذا كانت القيمة null أو 0 ---
  final num? quantityValue = visitData['quantity_sold'];
  _quantityController.text = (quantityValue == null || quantityValue == 0)
      ? '' // نص فارغ إذا كانت القيمة null أو 0
      : quantityValue.toString(); // وإلا، قم بتحويل القيمة إلى نص

  final num? cashValue = visitData['cash_collected'];
  final double cashDouble = (cashValue?.toDouble()) ?? 0.0; // تحويل آمن لـ double
  _cashController.text = (cashDouble == 0.0)
      ? '' // نص فارغ إذا كانت القيمة 0.0
      : cashDouble.toStringAsFixed(2); // وإلا، حولها لنص مع منزلتين عشريتين

  final num? debtValue = visitData['debt_paid'];
  final double debtDouble = (debtValue?.toDouble()) ?? 0.0; // تحويل آمن لـ double
  _debtPaidController.text = (debtDouble == 0.0)
      ? '' // نص فارغ إذا كانت القيمة 0.0
      : debtDouble.toStringAsFixed(2); // وإلا، حولها لنص مع منزلتين عشريتين
  // --- نهاية التعديل ---

  _notesController.text = (visitData['notes'] ?? visitData['no_sale_reason'] ?? '');
  _selectedProductVariantId = visitData['product_variant_id'] as int?;

  // +++ استخلاص وتخزين بيانات الموقع من الرد +++
  // نفترض أن بيانات المحل موجودة تحت مفتاح 'shop' في الرد
  final shopData = visitData['shop'];
  if (shopData is Map<String, dynamic>) {
    // استخدام as num? للتعامل الآمن مع الأنواع ثم toDouble()
    _shopLatitude = (shopData['latitude'] as num?)?.toDouble();
    _shopLongitude = (shopData['longitude'] as num?)?.toDouble();
    _shopLink = shopData['location_link'] as String?;
    _shopAddr = shopData['address'] as String?; // افترضنا اسم الحقل 'address' للعنوا
    developer.log('Loaded location data - Lat: $_shopLatitude, Lng: $_shopLongitude, Link: $_shopLink, Addr: $_shopAddr');
  } else {
    developer.log('Shop data not found or invalid in visit details response.');
    _shopLatitude = null;
    _shopLongitude = null;
    _shopLink = null;
    _shopAddr = null;
  }
  // ++++++++++++++++++++++++++++++++++++++++++++++++

  _error = null;
  _fetchProductsError = null;

  // إذا لم يتم تحديد منتج من الرد وكان outcome هو Sale، حاول تعيين الافتراضي
  if (_selectedOutcome == 'Sale' && _selectedProductVariantId == null) {
    _selectedProductVariantId = _findDefaultProductId();
  }
  // أو إذا كانت زيارة جديدة (404) ولم يتم اختيار outcome بعد
  else if (_selectedOutcome == null && _selectedProductVariantId == null) {
    _selectedProductVariantId = _findDefaultProductId();
  }

  // ملاحظة: تأكد من استدعاء _updateCalculatedInfo() بعد setState إذا لزم الأمر

             _updateCalculatedInfo();
          });
       } else if (response.statusCode == 404) {
           developer.log('No existing details found for visit ${widget.visitId}. This might be a new visit.');
           // زيارة جديدة، عين المنتج الافتراضي فقط
           if(mounted){
              setState(() {
                 _selectedProductVariantId = _findDefaultProductId();
                 // مسح أي بيانات موقع قديمة (غير محتمل لكن للاحتياط)
                 _shopLatitude = null;
                 _shopLongitude = null;
                 _shopLink = null;
                 _shopAddr = null;
              });
              _updateCalculatedInfo();
           }
       } else {
          developer.log('Failed to load visit details: ${response.statusCode}');
          if (mounted) setState(() { _error = 'فشل تحميل تفاصيل الزيارة (${response.statusCode})'; });
       }
    } catch(e, s) {
       developer.log('Error fetching visit details: ${e.toString()}', error: e, stackTrace: s);
       if (mounted) setState(() { _error = 'خطأ في تحميل تفاصيل الزيارة'; });
    }
  }


  // --- دالة تحديث المعلومات المحسوبة ---
  void _updateCalculatedInfo() {
     _updateExpectedSaleValue(); // حساب القيمة فقط، البونص صار مسؤولية السيرفر
  }

  
  // --- دالة حساب قيمة البيع المتوقعة ---
  void _updateExpectedSaleValue() {
     // ... (الكود كما هو بدون تغيير) ...
      double? expectedValue;
      final int? quantity = int.tryParse(_quantityController.text.trim());
      if (quantity != null && quantity > 0 && _selectedProductVariantId != null && _productVariants.isNotEmpty) {
         try { // Add try-catch for safety
           final selectedVariant = _productVariants.firstWhere( (variant) => variant['id'] == _selectedProductVariantId);
           if (selectedVariant['price_per_carton'] != null) {
             final double price = (selectedVariant['price_per_carton'] as num).toDouble();
             expectedValue = quantity * price;
           }
         } catch (e) {
           developer.log("Error finding selected variant price: $e");
           expectedValue = null; // Reset if variant not found
         }
      }
      if (mounted && _expectedSaleValue != expectedValue) {
         setState(() { _expectedSaleValue = expectedValue; });
      }
  }


  // --- دالة بناء الواجهة الرئيسية ---
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.shopName),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.map_outlined),
            tooltip: 'عرض الموقع على الخريطة',
            onPressed: (_shopLatitude == null && _shopLongitude == null && (_shopLink == null || _shopLink!.isEmpty))
              ? null // تعطيل الزر إذا لم تتوفر أي بيانات موقع
              : _openMap,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline, color: Colors.red, size: 50),
                        const SizedBox(height: 10),
                        Text('حدث خطأ: $_error', textAlign: TextAlign.center, style: TextStyle(color: Colors.red[700])),
                        const SizedBox(height: 20),
                        ElevatedButton.icon(
                            icon: const Icon(Icons.refresh),
                            label: const Text('إعادة المحاولة'),
                            onPressed: _fetchDataOnInit,
                        )
                      ],
                    ),
                  ),
                )
              : _buildVisitForm(), // عرض الفورم
    );
  }

  // --- دالة بناء محتوى الفورم ---
  Widget _buildVisitForm() {
     // ... (الكود كما هو مع إضافة const حيث أمكن) ...
      return SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column( crossAxisAlignment: CrossAxisAlignment.stretch, children: [
           Text('تسجيل نتيجة زيارة المحل:', style: Theme.of(context).textTheme.titleLarge),
           const SizedBox(height: 8),
           Text('الذمة الحالية: ${widget.shopBalance.toStringAsFixed(2)} د.أ'), // استخدام widget للذمة الممررة
           const Divider(height: 30),
           Text('نتيجة التفاعل الحالي:', style: Theme.of(context).textTheme.titleMedium),
           _buildOutcomeSelectionChips(),
           const Divider(height: 30),
           // استخدام Form فقط حول حقول البيع لتطبيق التحقق عند البيع فقط
           AnimatedSwitcher( duration: const Duration(milliseconds: 300), child: _buildConditionalFields(),),
           if (_selectedOutcome != null) const SizedBox(height: 30),
           if (_selectedOutcome != null) ElevatedButton(
              onPressed: _isSubmitting ? null : _validateAndSubmit,
              style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 15)),
              child: _isSubmitting
                   ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                   : const Text('حفظ النتيجة'),
              ),
           ],
        ),
       );
  }

  // --- دالة بناء الأجزاء الشرطية ---
  Widget _buildConditionalFields() {
      // ... (الكود كما هو مع إضافة const حيث أمكن) ...
       if (_selectedOutcome == 'Sale') {
        return Form( key: _formKey, child: Column( key: const ValueKey('Sale'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
           Text('تفاصيل البيع:', style: Theme.of(context).textTheme.titleMedium),
           const SizedBox(height: 15),
           _buildProductDropdown(),
           const SizedBox(height: 10),
           _buildNumericTextFormField( controller: _quantityController, labelText: 'عدد الكراتين *', icon: Icons.shopping_cart, validator: (value) { if (value == null || value.trim().isEmpty) { return 'الرجاء إدخال عدد الكراتين'; } final quantity = int.tryParse(value.trim()); if (quantity == null) { return 'الرجاء إدخال رقم صحيح'; } if (quantity <= 0) { return 'الرجاء إدخال كمية أكبر من صفر';} return null; }, onChanged: (value) { _updateCalculatedInfo(); }, ),
           const SizedBox(height: 10),
           if (_expectedSaleValue != null) Padding( padding: const EdgeInsets.only(bottom: 8.0), child: Text( 'المبلغ المطلوب للبضاعة: ${_expectedSaleValue!.toStringAsFixed(2)} د.أ', style: TextStyle(color: Theme.of(context).colorScheme.primary, fontStyle: FontStyle.italic), textAlign: TextAlign.center, ), ),
           _buildNumericTextFormField( controller: _cashController, labelText: 'الكاش المستلم *', icon: Icons.money, validator: (value) { if (value == null || value.trim().isEmpty) { return 'الرجاء إدخال الكاش المستلم'; } if (double.tryParse(value.trim()) == null) { return 'الرجاء إدخال مبلغ صحيح'; } if (double.parse(value.trim()) < 0) { return 'المبلغ لا يمكن أن يكون سالباً'; } return null; }, onChanged: (_) {} ),
           const SizedBox(height: 10),
           _buildNumericTextFormField( controller: _debtPaidController, labelText: 'تحصيل الذمة (اختياري)', icon: Icons.account_balance_wallet, validator: (value) { if (value != null && value.trim().isNotEmpty && double.tryParse(value.trim()) == null) { return 'الرجاء إدخال مبلغ صحيح'; } if (value != null && value.trim().isNotEmpty && double.parse(value.trim()) < 0) { return 'المبلغ لا يمكن أن يكون سالباً'; } return null; }, onChanged: (_) {} ),
           const SizedBox(height: 10),
           TextFormField( controller: _notesController, decoration: const InputDecoration(labelText: 'ملاحظات إضافية (اختياري)', prefixIcon: Icon(Icons.notes), border: OutlineInputBorder(),), maxLines: 2,),
           ] ), );
      } else if (_selectedOutcome == 'NoSale') {
        return Column( key: const ValueKey('NoSale'), crossAxisAlignment: CrossAxisAlignment.start, children: [ const Text('سبب عدم البيع / ملاحظات:', /*...*/), const SizedBox(height: 10), TextFormField( controller: _notesController, decoration: const InputDecoration(labelText: 'اذكر السبب أو أضف ملاحظة', /*...*/), maxLines: 3,), const SizedBox(height: 20), const Text('تحصيل الذمة (إن وجد):', /*...*/), const SizedBox(height: 10), _buildNumericTextFormField( controller: _debtPaidController, labelText: 'مبلغ تحصيل الذمة (اختياري)', icon: Icons.account_balance_wallet, validator: (value) {
          return null;
         /*...*/ }, onChanged: (_) {} ), ] );
      } else if (_selectedOutcome == 'Postponed') {
         return Column( key: const ValueKey('Postponed'), crossAxisAlignment: CrossAxisAlignment.start, children: [ const Text('سبب التأجيل / ملاحظة للمتابعة:', /*...*/), const SizedBox(height: 10), TextFormField( controller: _notesController, decoration: const InputDecoration(labelText: 'مثال: المحل مغلق، العودة 2م', /*...*/), maxLines: 3,), ] );
      } else { return const SizedBox.shrink(key: ValueKey('None')); } // Use SizedBox.shrink for empty space
  }

  // --- دالة بناء أزرار اختيار النتيجة ---
  Widget _buildOutcomeSelectionChips() {
     // ... (الكود كما هو مع إضافة const) ...
      return Wrap(
         spacing: 8.0, runSpacing: 8.0, alignment: WrapAlignment.spaceEvenly,
         children: [
           ChoiceChip(
             label: const Text('تم البيع (إنهاء)'), selected: _selectedOutcome == 'Sale',
             onSelected: (selected) { if (selected) { setState(() { _selectedOutcome = 'Sale'; _selectedProductVariantId = _findDefaultProductId(); _updateCalculatedInfo(); }); } },
             selectedColor: Colors.lightGreenAccent[100], shape: const StadiumBorder(),
             side: BorderSide(color: _selectedOutcome == 'Sale' ? Colors.green : Colors.grey),
             avatar: _selectedOutcome == 'Sale' ? Icon(Icons.check_circle, color: Colors.green[800], size: 18) : null,
           ),
           ChoiceChip(
             label: const Text('لم يتم البيع (إنهاء)'), selected: _selectedOutcome == 'NoSale',
             onSelected: (selected) { if (selected) { setState(() { _selectedOutcome = 'NoSale'; _expectedSaleValue = null; }); } },
             selectedColor: Colors.orangeAccent[100], shape: const StadiumBorder(),
             side: BorderSide(color: _selectedOutcome == 'NoSale' ? Colors.orange : Colors.grey),
             avatar: _selectedOutcome == 'NoSale' ? Icon(Icons.cancel, color: Colors.red[700], size: 18) : null,
           ),
           ChoiceChip(
              label: const Text('تأجيل / متابعة'), selected: _selectedOutcome == 'Postponed',
              onSelected: (selected) { if (selected) { setState(() { _selectedOutcome = 'Postponed'; _expectedSaleValue = null; }); } },
              selectedColor: Colors.lightBlueAccent[100], shape: const StadiumBorder(),
              side: BorderSide(color: _selectedOutcome == 'Postponed' ? Colors.blue : Colors.grey),
              avatar: _selectedOutcome == 'Postponed' ? Icon(Icons.watch_later, color: Colors.blue[700], size: 18) : null,
            ),
          ],
        );
  }

  // --- دالة بناء القائمة المنسدلة للمنتجات ---
  Widget _buildProductDropdown() {
     // ... (الكود كما هو مع إضافة const) ...
      if (_isFetchingProducts) return const Center(child: Padding(padding: EdgeInsets.symmetric(vertical: 24.0), child: CircularProgressIndicator()));
      if (_fetchProductsError != null && _fetchProductsError != _error) return Center(child: Padding(padding: const EdgeInsets.all(8.0), child: Text('خطأ تحميل المنتجات: $_fetchProductsError', style: const TextStyle(color: Colors.red))));
      if (_productVariants.isEmpty && _fetchProductsError == null) return const Center(child: Padding(padding: EdgeInsets.all(8.0), child: Text('لا توجد منتجات متاحة حالياً.')));

      return DropdownButtonFormField<int>(
          value: _selectedProductVariantId,
          isExpanded: true,
          decoration: const InputDecoration( labelText: 'اختر المنتج المباع *', prefixIcon: Icon(Icons.category), border: OutlineInputBorder(), contentPadding: EdgeInsets.symmetric(vertical: 15.0, horizontal: 10.0),),
          hint: const Text('اختر المنتج...'),
          items: _productVariants
           .where((variant) => variant['id'] != null && variant['id'] is int)
           .map<DropdownMenuItem<int>>((variant) { final int id = variant['id'] as int; final String name = variant['variant_name'] ?? 'غير معروف'; final double price = (variant['price_per_carton'] as num?)?.toDouble() ?? 0.0; return DropdownMenuItem<int>( value: id, child: Text('$name (${price.toStringAsFixed(2)} د.أ)', overflow: TextOverflow.ellipsis), ); }).toList(),
          onChanged: (int? newValue) {
             setState(() {
                _selectedProductVariantId = newValue;
                developer.log('Selected Product Variant ID: $_selectedProductVariantId');
                _updateCalculatedInfo();
             });
          },
          validator: (value) {
             if (_selectedOutcome == 'Sale' && value == null) {
                return 'الرجاء اختيار المنتج المباع';
             }
             return null;
          },
         );
  }

  // --- دالة بناء الحقول الرقمية ---
  Widget _buildNumericTextFormField({ required TextEditingController controller, required String labelText, required IconData icon, String? Function(String?)? validator, required final void Function(String) onChanged, }) {
     // ... (الكود كما هو مع إضافة const) ...
       return TextFormField(
         controller: controller,
         decoration: InputDecoration( labelText: labelText, prefixIcon: Icon(icon), border: const OutlineInputBorder(), ),
         keyboardType: const TextInputType.numberWithOptions(decimal: true),
         inputFormatters: <TextInputFormatter>[ FilteringTextInputFormatter.allow(RegExp(r'^\d+\.?\d{0,2}')), ],
         validator: validator,
         onChanged: onChanged,
       );
  }

  // --- دالة إظهار تأكيد الدين ---
  Future<bool> _showDebtConfirmationDialog(double difference) async {
     // ... (الكود كما هو مع إضافة const) ...
      if (!mounted) return false;
      final bool? result = await showDialog<bool>( context: context, barrierDismissible: false, builder: (BuildContext context) {
           return AlertDialog( title: const Text('تأكيد تسجيل ذمة'), content: Text('المبلغ المدخل أقل من قيمة البضاعة بمقدار ${difference.toStringAsFixed(2)} د.أ. هل تريد تسجيل هذا الفرق كذمة جديدة على المحل؟'), actions: <Widget>[
               TextButton( child: const Text('لا، تعديل المبلغ'), onPressed: () { Navigator.of(context).pop(false); }, ),
               TextButton( child: const Text('نعم، سجل كذمة'), onPressed: () { Navigator.of(context).pop(true); }, ), ], ); }, );
      return result ?? false;
  }

  // --- دالة التحقق والإرسال ---
  Future<void> _validateAndSubmit() async {
     // ... (الكود كما هو بدون تغيير) ...
      if (_isSubmitting || _selectedOutcome == null) return;

      if (_selectedOutcome == 'Sale') {
         if (_formKey.currentState == null || !_formKey.currentState!.validate()) {
           ScaffoldMessenger.of(context).showSnackBar(const SnackBar( content: Text('الرجاء تعبئة الحقول الإجبارية (*) بشكل صحيح.'), backgroundColor: Colors.orange, ));
           return;
         }
         final double cashEntered = double.parse(_cashController.text.trim());
         final double debtPaidEntered = double.tryParse(_debtPaidController.text.trim()) ?? 0.0;
         final int quantitySold = int.parse(_quantityController.text.trim());
         double currentExpectedValue = _expectedSaleValue ?? 0.0;
          if (currentExpectedValue <= 0 && quantitySold > 0) {
             final selectedVariant = _productVariants.firstWhere( (v) => v['id'] == _selectedProductVariantId, orElse: () => {});
             if (selectedVariant.isNotEmpty && selectedVariant['price_per_carton'] != null) {
                 currentExpectedValue = quantitySold * (selectedVariant['price_per_carton'] as num).toDouble();
             }
          }
         if (quantitySold > 0 && currentExpectedValue <= 0) {
           ScaffoldMessenger.of(context).showSnackBar(const SnackBar( content: Text('خطأ: لم يتم تحديد سعر المنتج بشكل صحيح.'), backgroundColor: Colors.red,));
           return;
         }
         if (cashEntered > currentExpectedValue) {
           ScaffoldMessenger.of(context).showSnackBar(SnackBar( content: Text('خطأ: الكاش (${cashEntered.toStringAsFixed(2)}) أكبر من قيمة البضاعة (${currentExpectedValue.toStringAsFixed(2)}).'), backgroundColor: Colors.orange, ));
           return;
         } else if (cashEntered < currentExpectedValue) {
           final double difference = currentExpectedValue - cashEntered;
           final bool confirmDebt = await _showDebtConfirmationDialog(difference);
           if (!confirmDebt) return;
         }
         await _performSubmit(cashEntered, debtPaidEntered, quantitySold, null, _notesController.text.trim().isNotEmpty ? _notesController.text.trim() : null);
      }
      else if (_selectedOutcome == 'NoSale') {
          final double debtPaidEntered = double.tryParse(_debtPaidController.text.trim()) ?? 0.0;
          final String? notesOrReason = _notesController.text.trim().isNotEmpty ? _notesController.text.trim() : null;
          if(debtPaidEntered < 0) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar( content: Text('مبلغ تحصيل الذمة لا يمكن أن يكون سالباً.'), backgroundColor: Colors.orange,)); return; }
          await _performSubmit(0.0, debtPaidEntered, 0, notesOrReason, notesOrReason);
      }
      else if (_selectedOutcome == 'Postponed') {
          final String? notesOrReason = _notesController.text.trim().isNotEmpty ? _notesController.text.trim() : null;
          if (notesOrReason == null || notesOrReason.isEmpty) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar( content: Text('الرجاء إدخال سبب التأجيل أو ملاحظة للمتابعة.'), backgroundColor: Colors.orange,)); return; }
          await _performSubmit(0.0, 0.0, 0, notesOrReason, notesOrReason);
      }
  }

  // --- دالة الإرسال الفعلية للـ API ---
  // --- دالة الإرسال الفعلية للـ API (معدلة لاستخدام print) ---
  Future<void> _performSubmit(
    double cashCollected, double debtPaid, int quantitySold,
    String? noSaleReason, String? notes
  ) async {
      setState(() { _isSubmitting = true; });

      Map<String, dynamic> payload = {
        'outcome': _selectedOutcome!,
        'cash_collected': cashCollected, 'debt_paid': debtPaid, 'quantity_sold': quantitySold,
        'no_sale_reason': noSaleReason, 'notes': notes,
        'product_variant_id': (quantitySold > 0) ? _selectedProductVariantId : null,
      };
      payload.removeWhere((key, value) => value == null);

      final url = Uri.parse('http://10.0.2.2:5000/visits/${widget.visitId}'); // استخدم IP جهازك
      Map<String, String> headers = {}; // تعريف أولي

      try { // Main try block
        headers = await getAuthenticatedHeaders(needsContentType: false);
        headers = { ...headers, 'Content-Type': 'application/json; charset=UTF-8'};

        http.Response? response; // تعريف متغير الاستجابة
        try { // --- Inner try-catch for http.put ---
             response = await http.put(
                url,
                headers: headers,
                body: jsonEncode(payload)
             ).timeout(const Duration(seconds: 20)); // Timeout لا يزال 20 ثانية
        } catch (httpError) { // التقاط خطأ الإرسال نفسه
            // ارمي الخطأ مرة أخرى ليتم التقاطه بواسطة الـ catch الرئيسي وعرض SnackBar
            throw Exception("Failed during HTTP PUT request: $httpError");
        }
        // --- End inner try-catch ---

        if (!mounted) {
          // قد تحتاج لإيقاف مؤشر التحميل هنا أيضاً إذا لم يتم الدخول لـ finally
          if (mounted) setState(() { _isSubmitting = false; });
          return;
        }

        // --- معالجة الرد (الكود المتبقي كما هو) ---
        if (response.statusCode == 200) {
           // ... (SnackBar and Navigator.pop) ...
            if (mounted) {
               ScaffoldMessenger.of(context).showSnackBar(const SnackBar( content: Text('تم حفظ نتيجة الزيارة بنجاح!'), backgroundColor: Colors.green, ));
               Navigator.pop(context, true);
            }
        } else if (response.statusCode == 401) {
           await handleUnauthorized(context);
           // لا تنس إيقاف التحميل هنا أيضاً
           if (mounted) setState(() { _isSubmitting = false; });
        } else {
           // ... (SnackBar for other errors) ...
            String errorMessage = 'فشل حفظ الزيارة (رمز: ${response.statusCode})';
            try { final errorData = jsonDecode(response.body); if (errorData is Map && errorData.containsKey('message')) { errorMessage = errorData['message']; } } catch (_) {}
            if (mounted) {
               ScaffoldMessenger.of(context).showSnackBar(SnackBar( content: Text('خطأ: $errorMessage'), backgroundColor: Colors.red, ));
               // لا تنس إيقاف التحميل هنا أيضاً
               setState(() { _isSubmitting = false; });
            }
        }
        // --- نهاية معالجة الرد ---

        } catch (error) { // Main catch block
         if (!mounted) return;
         // ... (SnackBar for general errors) ...
         String errorMsg = 'حدث خطأ في الاتصال بالخادم.';
         if (error is TimeoutException) {
             errorMsg = 'انتهت مهلة الاتصال بالخادم.';
         } else if (error is SocketException) {
             errorMsg = 'خطأ في الشبكة، تأكد من اتصالك بالإنترنت أو بالـ Backend.';
         } else {
             // استخدم رسالة الخطأ من الـ Exception الداخلي إذا كانت موجودة
             errorMsg = error.toString().replaceFirst("Exception: ", "");
             // errorMsg = 'حدث خطأ غير متوقع: ${error.runtimeType}';
         }
         ScaffoldMessenger.of(context).showSnackBar(SnackBar( content: Text(errorMsg), backgroundColor: Colors.red, ));
         // تأكد من إيقاف التحميل هنا أيضاً
         // setState(() { _isSubmitting = false; }); // يتم في finally
      } finally {
         if (mounted) { setState(() { _isSubmitting = false; }); }
      }
  }
  // --- نهاية دالة الإرسال ---


   // --- دالة فتح الخريطة (معدلة لتقرأ من متغيرات الحالة) ---
  Future<void> _openMap() async {
    // --- استخدام متغيرات الحالة الجديدة ---
    final double? lat = _shopLatitude;
    final double? lng = _shopLongitude;
    final String? link = _shopLink;
    final String title = widget.shopName; // اسم المحل لا يزال من الـ widget
    final String? description = _shopAddr; // العنوان النصي المحمل
    // -------------------------------------

    developer.log('--- _openMap Triggered ---');
    developer.log('Checking Lat from state: $lat');
    developer.log('Checking Lng from state: $lng');
    developer.log('Checking Link from state: $link');
    developer.log('Checking Title from widget: $title');
    developer.log('Checking Description from state: $description');

    try {
      if (lat != null && lng != null) {
        developer.log('Coordinates found, attempting to use map_launcher');
        // لا حاجة لجلب الخرائط المثبتة هنا، showMarker يتعامل معها
        // final availableMaps = await MapLauncher.installedMaps;

        // استخدام showMarker مباشرةً لعرض دبوس الموقع والسماح للمستخدم باختيار التطبيق
        await MapLauncher.showMarker(
          mapType: MapType.google, // يمكنك تحديد نوع الخريطة المفضل أو تركه تلقائياً
          coords: Coords(lat, lng),
          title: title,
          description: description ?? '',
        );

      } else if (link != null && link.trim().isNotEmpty) {
        developer.log('Coordinates not found, attempting to launch manual link: $link');
        final Uri url = Uri.parse(link.trim());

        // استخدام launchUrl مباشرة، سيعيد false إذا فشل
        if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
           developer.log('Could not launch URL: $link');
           if (mounted) { ScaffoldMessenger.of(context).showSnackBar(
               SnackBar(content: Text('لا يمكن فتح الرابط: $link'), backgroundColor: Colors.red),
           );}
        }
      } else {
         developer.log('No location data available (coordinates or link).');
         if(mounted) { ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('لا تتوفر بيانات موقع لهذا المحل.'), backgroundColor: Colors.orange),
        );
      }}
    } catch (e, s) {
      developer.log('Error opening map/link: $e', error: e, stackTrace: s);
       if(mounted) { ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('حدث خطأ عند محاولة عرض الموقع: ${e.toString()}'), backgroundColor: Colors.red),
      );
    }} finally {
       // if (mounted) setState(() { /* إعادة تعيين متغير الحالة إذا أضفته */ });
    }
  }
  // --- نهاية دالة فتح الخريطة ---

} // نهاية كلاس _VisitScreenState