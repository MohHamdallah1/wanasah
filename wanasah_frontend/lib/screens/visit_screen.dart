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
import 'package:wanasah_frontend/services/auth_utils.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

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
    super.key,
  });

  @override
  State<VisitScreen> createState() => _VisitScreenState();
}

// --- تعريف الكلاس State ---
class _VisitScreenState extends State<VisitScreen> {
  final _formKey = GlobalKey<FormState>();

  // --- متغيرات الحالة للحقول ---
  String? _selectedOutcome;
  final _cashController = TextEditingController();
  final _debtPaidController = TextEditingController();
  final _notesController = TextEditingController();

  // +++ العقل الجديد: خريطة سلة المشتريات (تدعم كراتين وحبات) +++
  // المفتاح: Product Variant ID | القيمة: خريطة تحتوي 'cartons' و 'packs'
  final Map<int, Map<String, int>> _cartQuantities = {};
  // قائمة لتخزين المرتجعات (يمكن إضافة أكثر من نوع تلف لنفس المنتج)
  final List<Map<String, dynamic>> _returnsList = [];

  // متغيرات الحسابات المباشرة
  double _totalExpectedValue = 0.0;
  final int _totalBonusItems = 0; // سيتم ربطها بمحرك العروض لاحقاً

  // --- متغيرات الحالة العامة والتحميل ---
  bool _isSubmitting = false;
  List<Map<String, dynamic>> _productVariants = [];
  bool _isFetchingProducts = true;
  String? _fetchProductsError;
  bool _isLoading = true;
  String? _error;

  // --- متغيرات حالة بيانات الموقع ---
  double? _shopLatitude;
  double? _shopLongitude;
  String? _shopLink;
  String? _shopAddr;

  // --- متغير الصلاحية (الضوء الأخضر) ---
  bool _isAuthorizedToSell = false;

  // +++ دوال العدادات الجديدة +++

  // تحديث كمية صنف معين (كراتين أو حبات)
  void _updateCartItem(int variantId, {int? cartons, int? packs}) {
    setState(() {
      _cartQuantities[variantId] ??= {'cartons': 0, 'packs': 0};

      if (cartons != null) _cartQuantities[variantId]!['cartons'] = cartons;
      if (packs != null) _cartQuantities[variantId]!['packs'] = packs;

      // إذا الكراتين والحبات صفر، احذف المنتج من السلة لتنظيفها
      if (_cartQuantities[variantId]!['cartons'] == 0 &&
          _cartQuantities[variantId]!['packs'] == 0) {
        _cartQuantities.remove(variantId);
      }
      _calculateLiveTotals();
    });
  }

  // --- الحساب المباشر والحي للإجمالي ---
  void _calculateLiveTotals() {
    double tempTotal = 0.0;

    _cartQuantities.forEach((variantId, qtyMap) {
      final variant = _productVariants.firstWhere(
        (v) => v['id'] == variantId,
        orElse: () => {},
      );
      if (variant.isNotEmpty) {
        double cartonPrice =
            (variant['price_per_carton'] as num?)?.toDouble() ?? 0.0;
        double packPrice =
            (variant['price_per_pack'] as num?)?.toDouble() ?? 0.0;

        tempTotal +=
            (cartonPrice * qtyMap['cartons']!) + (packPrice * qtyMap['packs']!);
      }
    });

    setState(() {
      _totalExpectedValue = tempTotal;
    });
  }

  // --- دوال دورة حياة الويدجت ---
  @override
  void initState() {
    super.initState();
    _fetchDataOnInit();
  }

  @override
  void dispose() {
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
    setState(() {
      _isLoading = true;
      _error = null;
      _fetchProductsError = null;
    });

    try {
      developer.log("Starting initial data fetch...");

      // +++ قراءة الصلاحية من الخزنة الآمنة +++
      const storage = FlutterSecureStorage();
      String? authStr = await storage.read(key: 'is_authorized');
      setState(() {
        // هذا السطر بيقفل الدنيا (False) إذا كانت الخزنة فارغة أو فيها أي إشي غير الكلمة 'true'
        _isAuthorizedToSell = (authStr == 'true');
      });

      // أولاً: جلب قائمة المنتجات
      await _fetchProductVariants();

      // ثانياً: جلب تفاصيل الزيارة (إذا نجحت المنتجات)
      if (mounted && _fetchProductsError == null) {
        developer.log(
          "Product fetch successful, proceeding to load visit details...",
        );
        await _loadVisitDetails();
      } else if (mounted && _fetchProductsError != null) {
        developer.log("Product fetch failed, setting screen error.");
        setState(() {
          _error = _fetchProductsError;
        });
      }
    } catch (e, s) {
      developer.log(
        "Unexpected error during initial data fetch.",
        error: e,
        stackTrace: s,
      );
      if (mounted) {
        setState(() {
          _error = 'خطأ غير متوقع أثناء تحميل بيانات الشاشة';
        });
      }
    } finally {
      // إيقاف التحميل الكلي
      if (mounted) {
        developer.log(
          "Finished initial data fetch. Setting isLoading to false.",
        );
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  // --- دالة جلب المنتجات ---
  Future<void> _fetchProductVariants() async {
    if (!mounted) return;
    setState(() {
      _isFetchingProducts = true;
      _fetchProductsError = null;
    });

    final url = Uri.parse('http://10.0.2.2:5000/product_variants');
    developer.log('Fetching product variants from: $url');

    try {
      final headers = await getAuthenticatedHeaders(needsContentType: false);
      final response = await http
          .get(url, headers: headers)
          .timeout(const Duration(seconds: 15));
      if (!mounted) return;

      if (response.statusCode == 401) {
        await handleUnauthorized(context);
        if (mounted) {
          setState(() {
            _fetchProductsError = 'الجلسة غير صالحة';
            _isFetchingProducts = false;
          });
          return;
        }
      }

      if (response.statusCode == 200) {
        final List<dynamic> decodedData = jsonDecode(response.body);
        final List<Map<String, dynamic>> variantsList =
            List<Map<String, dynamic>>.from(
              decodedData.whereType<Map<String, dynamic>>(),
            );

        setState(() {
          _productVariants = variantsList;
          _isFetchingProducts = false;
          _fetchProductsError = null;
          // لا نحدد الافتراضي هنا، نتركه لـ _loadVisitDetails أو للقيمة الأولية
        });
      } else {
        developer.log(
          'Failed to load product variants. Status: ${response.statusCode}',
        );
        if (mounted) {
          setState(() {
            _fetchProductsError =
                'فشل تحميل قائمة المنتجات (${response.statusCode})';
            _isFetchingProducts = false;
          });
        }
      }
    } catch (error, stacktrace) {
      developer.log(
        'Error fetching product variants: ${error.toString()}',
        error: error,
        stackTrace: stacktrace,
      );
      if (!mounted) return;
      setState(() {
        _fetchProductsError = 'خطأ في الاتصال عند تحميل المنتجات';
        _isFetchingProducts = false;
      });
    }
  }

  // --- دالة جلب تفاصيل الزيارة الحالية (معدلة لتخزين بيانات الموقع) ---
  Future<void> _loadVisitDetails() async {
    if (!mounted) return;

    final url = Uri.parse(
      'http://10.0.2.2:5000/visits/${widget.visitId}',
    ); // <-- تأكد من الـ Base URL
    developer.log('Fetching visit details from: $url');

    try {
      final headers = await getAuthenticatedHeaders(needsContentType: false);
      final response = await http
          .get(url, headers: headers)
          .timeout(const Duration(seconds: 15));
      if (!mounted) return;

      if (response.statusCode == 401) {
        await handleUnauthorized(context);
        if (mounted) {
          setState(() {
            _error = 'الجلسة غير صالحة';
          });
        }
        return;
      }

      if (response.statusCode == 200) {
        final visitData = jsonDecode(response.body);
        developer.log('Visit details received: $visitData');

        // --- تحديث الحالة بالبيانات المستلمة لتعبئة الحقول ---
        // --- تحديث الحالة بالبيانات المستلمة لتعبئة الحقول ---
        setState(() {
          _selectedOutcome = visitData['outcome'];

          // +++ تعبئة سلة المشتريات (العقل الجديد) بدلا من الحقل القديم +++
          final num? quantityValue = visitData['quantity_sold'];
          final int? variantId = visitData['product_variant_id'] as int?;
          if (quantityValue != null && quantityValue > 0 && variantId != null) {
            _cartQuantities[variantId] = {
              'cartons': quantityValue.toInt(),
              'packs': 0,
            };
          }

          final num? cashValue = visitData['cash_collected'];
          final double cashDouble = (cashValue?.toDouble()) ?? 0.0;
          _cashController.text =
              (cashDouble == 0.0) ? '' : cashDouble.toStringAsFixed(2);

          final num? debtValue = visitData['debt_paid'];
          final double debtDouble = (debtValue?.toDouble()) ?? 0.0;
          _debtPaidController.text =
              (debtDouble == 0.0) ? '' : debtDouble.toStringAsFixed(2);

          _notesController.text =
              (visitData['notes'] ?? visitData['no_sale_reason'] ?? '');

          // +++ استخلاص بيانات الموقع +++
          final shopData = visitData['shop'];
          if (shopData is Map<String, dynamic>) {
            _shopLatitude = (shopData['latitude'] as num?)?.toDouble();
            _shopLongitude = (shopData['longitude'] as num?)?.toDouble();
            _shopLink = shopData['location_link'] as String?;
            _shopAddr = shopData['address'] as String?;
          } else {
            _shopLatitude = null;
            _shopLongitude = null;
            _shopLink = null;
            _shopAddr = null;
          }

          _error = null;
          _fetchProductsError = null;

          _calculateLiveTotals(); // استدعاء الحسابات الجديدة
        });
      } else if (response.statusCode == 404) {
        if (mounted) {
          setState(() {
            _cartQuantities.clear(); // تصفير السلة للزيارة الجديدة
            _shopLatitude = null;
            _shopLongitude = null;
            _shopLink = null;
            _shopAddr = null;
          });
          _calculateLiveTotals(); // استدعاء الحسابات الجديدة
        }
      } else {
        if (mounted) {
          setState(() {
            _error = 'فشل تحميل تفاصيل الزيارة (${response.statusCode})';
          });
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'خطأ في تحميل تفاصيل الزيارة';
        });
      }
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
            onPressed:
                (_shopLatitude == null &&
                        _shopLongitude == null &&
                        (_shopLink == null || _shopLink!.isEmpty))
                    ? null // تعطيل الزر إذا لم تتوفر أي بيانات موقع
                    : _openMap,
          ),
        ],
      ),
      body:
          _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(
                        Icons.error_outline,
                        color: Colors.red,
                        size: 50,
                      ),
                      const SizedBox(height: 10),
                      Text(
                        'حدث خطأ: $_error',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.red[700]),
                      ),
                      const SizedBox(height: 20),
                      ElevatedButton.icon(
                        icon: const Icon(Icons.refresh),
                        label: const Text('إعادة المحاولة'),
                        onPressed: _fetchDataOnInit,
                      ),
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
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'الذمة الحالية: ${widget.shopBalance.toStringAsFixed(2)} د.أ',
          ), // استخدام widget للذمة الممررة
          const Divider(height: 30),
          Text(
            'نتيجة التفاعل الحالي:',
            style: Theme.of(context).textTheme.titleMedium,
          ),

          // +++ قفل الشاشة بناءً على الصلاحية +++
          _isAuthorizedToSell
              ? _buildOutcomeSelectionChips()
              : Container(
                margin: const EdgeInsets.symmetric(vertical: 10),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.orange[50],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.orange),
                ),
                child: Row(
                  children: [
                    Icon(Icons.lock_outline, color: Colors.orange[800]),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'غير مصرح لك بإجراء عمليات بيع حالياً. بانتظار تفعيل خط السير من الإدارة.',
                        style: TextStyle(
                          color: Colors.orange[800],
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

          // +++++++++++++++++++++++++++++++++++++
          const Divider(height: 30),
          // استخدام Form فقط حول حقول البيع لتطبيق التحقق عند البيع فقط
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 300),
            child: _buildConditionalFields(),
          ),
          if (_selectedOutcome != null && _isAuthorizedToSell)
            const SizedBox(height: 30),
          if (_selectedOutcome != null && _isAuthorizedToSell)
            ElevatedButton(
              onPressed: _isSubmitting ? null : _validateAndSubmit,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 15),
              ),
              child:
                  _isSubmitting
                      ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(
                          color: Colors.white,
                          strokeWidth: 2,
                        ),
                      )
                      : const Text('حفظ النتيجة'),
            ),
        ],
      ),
    );
  }

  // --- دالة بناء الأجزاء الشرطية (الجديدة كلياً) ---
  Widget _buildConditionalFields() {
    if (_selectedOutcome == 'Sale') {
      return Form(
        key: _formKey,
        child: Column(
          key: const ValueKey('Sale'),
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'المنتجات المباعة (أضف الكميات):',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 15),

            // +++ قائمة المنتجات والعدادات الذكية +++
            _buildProductsList(),
            const SizedBox(height: 15),

            // +++ شريط الحساب المباشر (الفاتورة الحية) +++
            _buildLiveCalculationBar(),
            const SizedBox(height: 20),

            // +++ الأمور المالية +++
            _buildNumericTextFormField(
              controller: _cashController,
              labelText: 'الكاش المستلم *',
              icon: Icons.money,
              validator: (value) {
                // 1. إضافة الأقواس لحل مشكلة التنسيق وتوضيح المنطق البرمجي
                if (value == null || value.trim().isEmpty) {
                  return 'الرجاء إدخال الكاش المستلم';
                }

                // 2. تحسين الأداء بتخزين القيمة المحولة لمنع تكرار الـ parsing
                final parsedValue = double.tryParse(value.trim());

                if (parsedValue == null) {
                  return 'الرجاء إدخال مبلغ صحيح';
                }

                if (parsedValue < 0) {
                  return 'المبلغ لا يمكن أن يكون سالباً';
                }

                return null;
              },
              onChanged: (_) {},
            ),
            const SizedBox(height: 10),
            _buildNumericTextFormField(
              controller: _debtPaidController,
              labelText: 'تحصيل الذمة (اختياري)',
              icon: Icons.account_balance_wallet,
              validator: (value) {
                if (value != null &&
                    value.trim().isNotEmpty &&
                    double.tryParse(value.trim()) == null) {
                  return 'الرجاء إدخال مبلغ صحيح';
                }

                if (value != null &&
                    value.trim().isNotEmpty &&
                    double.parse(value.trim()) < 0) {
                  return 'المبلغ لا يمكن أن يكون سالباً';
                }

                return null;
              },
              onChanged: (_) {},
            ),
            const SizedBox(height: 10),
            TextFormField(
              controller: _notesController,
              decoration: const InputDecoration(
                labelText: 'ملاحظات إضافية (اختياري)',
                prefixIcon: Icon(Icons.notes),
                border: OutlineInputBorder(),
              ),
              maxLines: 2,
            ),
          ],
        ),
      );
    } else if (_selectedOutcome == 'NoSale') {
      return Column(
        key: const ValueKey('NoSale'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('سبب عدم البيع / ملاحظات:'),
          const SizedBox(height: 10),
          TextFormField(
            controller: _notesController,
            decoration: const InputDecoration(
              labelText: 'اذكر السبب أو أضف ملاحظة',
              border: OutlineInputBorder(),
            ),
            maxLines: 3,
          ),
          const SizedBox(height: 20),
          const Text('تحصيل الذمة (إن وجد):'),
          const SizedBox(height: 10),
          _buildNumericTextFormField(
            controller: _debtPaidController,
            labelText: 'مبلغ تحصيل الذمة (اختياري)',
            icon: Icons.account_balance_wallet,
            validator: (value) => null,
            onChanged: (_) {},
          ),
        ],
      );
    } else if (_selectedOutcome == 'Postponed') {
      return Column(
        key: const ValueKey('Postponed'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('سبب التأجيل / ملاحظة للمتابعة:'),
          const SizedBox(height: 10),
          TextFormField(
            controller: _notesController,
            decoration: const InputDecoration(
              labelText: 'مثال: المحل مغلق، العودة 2م',
              border: OutlineInputBorder(),
            ),
            maxLines: 3,
          ),
        ],
      );
    } else {
      return const SizedBox.shrink(key: ValueKey('None'));
    }
  }

  // --- دالة قائمة المنتجات والعدادات المباشرة (تصميم Compact Card) ---
  Widget _buildProductsList() {
    if (_isFetchingProducts) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: 24.0),
          child: CircularProgressIndicator(),
        ),
      );
    }
    if (_fetchProductsError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(8.0),
          child: Text(
            'خطأ تحميل المنتجات: $_fetchProductsError',
            style: const TextStyle(color: Colors.red),
          ),
        ),
      );
    }
    if (_productVariants.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(8.0),
          child: Text('لا توجد منتجات متاحة حالياً.'),
        ),
      );
    }

    return ListView.separated(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: _productVariants.length,
      separatorBuilder:
          (context, index) =>
              const SizedBox(height: 12), // فراغ أنيق بين الكروت
      itemBuilder: (context, index) {
        final variant = _productVariants[index];
        final int id = variant['id'] as int;
        final String name = variant['variant_name'] ?? 'غير معروف';
        final double cartonPrice =
            (variant['price_per_carton'] as num?)?.toDouble() ?? 0.0;
        final double packPrice =
            (variant['price_per_pack'] as num?)?.toDouble() ?? 0.0;

        final qtyMap = _cartQuantities[id] ?? {'cartons': 0, 'packs': 0};
        final int currentCartons = qtyMap['cartons']!;
        final int currentPacks = qtyMap['packs']!;
        final bool isSelected = currentCartons > 0 || currentPacks > 0;

        return Container(
          decoration: BoxDecoration(
            color:
                isSelected
                    ? Colors.blue.shade50.withValues(alpha: 0.4)
                    : Colors.white,
            border: Border.all(
              color: isSelected ? Colors.blue.shade300 : Colors.grey.shade300,
              width: isSelected ? 1.5 : 1,
            ),
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              if (isSelected)
                BoxShadow(
                  color: Colors.blue..withValues(alpha: 0.5),
                  blurRadius: 8,
                  offset: const Offset(0, 4),
                ),
            ],
          ),
          padding: const EdgeInsets.all(12.0),
          child: Column(
            children: [
              // 1. اسم المنتج والأسعار مع زر التوالف والعينات
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: Colors.blue.shade100,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(
                      Icons.inventory_2_outlined,
                      color: Colors.blue.shade800,
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 16,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '📦 ${cartonPrice.toStringAsFixed(2)}  |  🍬 ${packPrice.toStringAsFixed(2)}',
                          style: TextStyle(
                            color: Colors.grey.shade700,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                  // +++ زر التوالف والعينات +++
                  TextButton.icon(
                    onPressed:
                        () => _showExtraOptionsSheet(
                          id,
                          name,
                          variant['max_samples'] as int? ?? 0,
                        ),
                    icon: const Icon(Icons.more_vert, size: 18),
                    label: const Text(
                      'توالف/عينات',
                      style: TextStyle(fontSize: 12),
                    ),
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.orange.shade700,
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                    ),
                  ),
                ],
              ),
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8.0),
                child: Divider(height: 1),
              ),
              // 2. العدادات المدمجة (كراتين + حبات)
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  // عداد الكراتين
                  _buildCompactCounter(
                    'كرتونة',
                    '📦',
                    currentCartons,
                    () => _updateCartItem(
                      id,
                      cartons: currentCartons > 0 ? currentCartons - 1 : 0,
                    ),
                    () => _updateCartItem(id, cartons: currentCartons + 1),
                    () => _showNumpadDialog(
                      id,
                      name,
                      'كرتونة',
                      currentCartons,
                      isCarton: true,
                    ),
                  ),
                  Container(
                    width: 1,
                    height: 40,
                    color: Colors.grey.shade300,
                  ), // فاصل عمودي أنيق
                  // عداد الحبات
                  _buildCompactCounter(
                    'حبة',
                    '🍬',
                    currentPacks,
                    () => _updateCartItem(
                      id,
                      packs: currentPacks > 0 ? currentPacks - 1 : 0,
                    ),
                    () => _updateCartItem(id, packs: currentPacks + 1),
                    () => _showNumpadDialog(
                      id,
                      name,
                      'حبة',
                      currentPacks,
                      isCarton: false,
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }

  // --- ويدجت مساعدة للعداد المصغر ---
  Widget _buildCompactCounter(
    String label,
    String emoji,
    int qty,
    VoidCallback onMinus,
    VoidCallback onPlus,
    VoidCallback onTapNum,
  ) {
    final bool hasQty = qty > 0;
    return Column(
      children: [
        Text(
          '$emoji $label',
          style: TextStyle(
            fontSize: 12,
            color: Colors.grey.shade600,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 4),
        Row(
          children: [
            InkWell(
              onTap: hasQty ? onMinus : null,
              child: Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: hasQty ? Colors.red.shade50 : Colors.grey.shade100,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Icon(
                  Icons.remove,
                  size: 20,
                  color: hasQty ? Colors.red : Colors.grey.shade400,
                ),
              ),
            ),
            GestureDetector(
              onTap: onTapNum,
              child: Container(
                width: 45,
                alignment: Alignment.center,
                child: Text(
                  '$qty',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: hasQty ? Colors.green.shade700 : Colors.black87,
                  ),
                ),
              ),
            ),
            InkWell(
              onTap: onPlus,
              child: Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: Colors.green.shade50,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Icon(Icons.add, size: 20, color: Colors.green),
              ),
            ),
          ],
        ),
      ],
    );
  }

  // --- نافذة الإدخال اليدوي للسرعة (محدثة) ---
  Future<void> _showNumpadDialog(
    int variantId,
    String productName,
    String unitName,
    int currentQty, {
    required bool isCarton,
  }) async {
    final TextEditingController qtyController = TextEditingController(
      text: currentQty > 0 ? currentQty.toString() : '',
    );
    await showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(15),
          ),
          title: Text(
            'إدخال عدد الـ $unitName',
            style: const TextStyle(fontSize: 16),
          ),
          content: TextField(
            controller: qtyController,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: const InputDecoration(
              hintText: 'الكمية',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            autofocus: true,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('إلغاء', style: TextStyle(color: Colors.red)),
            ),
            ElevatedButton(
              onPressed: () {
                final int? newQty = int.tryParse(qtyController.text.trim());
                if (newQty != null && newQty >= 0) {
                  isCarton
                      ? _updateCartItem(variantId, cartons: newQty)
                      : _updateCartItem(variantId, packs: newQty);
                } else if (qtyController.text.trim().isEmpty) {
                  isCarton
                      ? _updateCartItem(variantId, cartons: 0)
                      : _updateCartItem(variantId, packs: 0);
                }
                Navigator.pop(context);
              },
              child: const Text('تأكيد'),
            ),
          ],
        );
      },
    );
  }

  // --- شريط الحساب المباشر العائم (النتيجة النهائية) ---
  Widget _buildLiveCalculationBar() {
    if (_totalExpectedValue <= 0) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.blue[50],
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.blue.shade200, width: 2),
      ),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'إجمالي الفاتورة:',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
              ),
              Text(
                '${_totalExpectedValue.toStringAsFixed(2)} د.أ',
                style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 20,
                  color: Colors.blue[800],
                ),
              ),
            ],
          ),
          const Divider(),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'البونص المستحق:',
                style: TextStyle(
                  color: Colors.green,
                  fontWeight: FontWeight.bold,
                ),
              ),
              Text(
                '$_totalBonusItems حبة (قريباً)',
                style: const TextStyle(
                  color: Colors.green,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // --- دالة بناء أزرار اختيار النتيجة (محدثة) ---
  Widget _buildOutcomeSelectionChips() {
    return Wrap(
      spacing: 8.0,
      runSpacing: 8.0,
      alignment: WrapAlignment.spaceEvenly,
      children: [
        ChoiceChip(
          label: const Text('تم البيع (إنهاء)'),
          selected: _selectedOutcome == 'Sale',
          onSelected: (selected) {
            if (selected) {
              setState(() {
                _selectedOutcome = 'Sale';
                _calculateLiveTotals(); // تحديث الحسابات للجديد
              });
            }
          },
          selectedColor: Colors.lightGreenAccent[100],
          shape: const StadiumBorder(),
          side: BorderSide(
            color: _selectedOutcome == 'Sale' ? Colors.green : Colors.grey,
          ),
          avatar:
              _selectedOutcome == 'Sale'
                  ? Icon(Icons.check_circle, color: Colors.green[800], size: 18)
                  : null,
        ),
        ChoiceChip(
          label: const Text('لم يتم البيع (إنهاء)'),
          selected: _selectedOutcome == 'NoSale',
          onSelected: (selected) {
            if (selected) {
              setState(() {
                _selectedOutcome = 'NoSale';
                _cartQuantities.clear(); // تفريغ السلة بدل تصفير المتغير القديم
                _calculateLiveTotals();
              });
            }
          },
          selectedColor: Colors.orangeAccent[100],
          shape: const StadiumBorder(),
          side: BorderSide(
            color: _selectedOutcome == 'NoSale' ? Colors.orange : Colors.grey,
          ),
          avatar:
              _selectedOutcome == 'NoSale'
                  ? Icon(Icons.cancel, color: Colors.red[700], size: 18)
                  : null,
        ),
        ChoiceChip(
          label: const Text('تأجيل / متابعة'),
          selected: _selectedOutcome == 'Postponed',
          onSelected: (selected) {
            if (selected) {
              setState(() {
                _selectedOutcome = 'Postponed';
                _cartQuantities.clear();
                _calculateLiveTotals();
              });
            }
          },
          selectedColor: Colors.lightBlueAccent[100],
          shape: const StadiumBorder(),
          side: BorderSide(
            color: _selectedOutcome == 'Postponed' ? Colors.blue : Colors.grey,
          ),
          avatar:
              _selectedOutcome == 'Postponed'
                  ? Icon(Icons.watch_later, color: Colors.blue[700], size: 18)
                  : null,
        ),
      ],
    );
  }

  // --- دالة بناء الحقول الرقمية ---
  Widget _buildNumericTextFormField({
    required TextEditingController controller,
    required String labelText,
    required IconData icon,
    String? Function(String?)? validator,
    required final void Function(String) onChanged,
  }) {
    // ... (الكود كما هو مع إضافة const) ...
    return TextFormField(
      controller: controller,
      decoration: InputDecoration(
        labelText: labelText,
        prefixIcon: Icon(icon),
        border: const OutlineInputBorder(),
      ),
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: <TextInputFormatter>[
        FilteringTextInputFormatter.allow(RegExp(r'^\d+\.?\d{0,2}')),
      ],
      validator: validator,
      onChanged: onChanged,
    );
  }

  // --- دالة إظهار تأكيد الدين ---
  Future<bool> _showDebtConfirmationDialog(double difference) async {
    // ... (الكود كما هو مع إضافة const) ...
    if (!mounted) return false;
    final bool? result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('تأكيد تسجيل ذمة'),
          content: Text(
            'المبلغ المدخل أقل من قيمة البضاعة بمقدار ${difference.toStringAsFixed(2)} د.أ. هل تريد تسجيل هذا الفرق كذمة جديدة على المحل؟',
          ),
          actions: <Widget>[
            TextButton(
              child: const Text('لا، تعديل المبلغ'),
              onPressed: () {
                Navigator.of(context).pop(false);
              },
            ),
            TextButton(
              child: const Text('نعم، سجل كذمة'),
              onPressed: () {
                Navigator.of(context).pop(true);
              },
            ),
          ],
        );
      },
    );
    return result ?? false;
  }

  // --- دالة التحقق والإرسال الذكية ---
  Future<void> _validateAndSubmit() async {
    if (_isSubmitting || _selectedOutcome == null) return;

    if (_selectedOutcome == 'Sale') {
      if (_formKey.currentState == null || !_formKey.currentState!.validate()) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('الرجاء تعبئة الحقول الإجبارية (*) بشكل صحيح.'),
            backgroundColor: Colors.orange,
          ),
        );
        return;
      }

      // التأكد من وجود صنف واحد على الأقل في السلة
      if (_cartQuantities.isEmpty ||
          _cartQuantities.values.every(
            (qtyMap) => qtyMap['cartons']! <= 0 && qtyMap['packs']! <= 0,
          )) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('الرجاء إضافة كمية لمنتج واحد على الأقل.'),
            backgroundColor: Colors.orange,
          ),
        );
        return;
      }

      final double cashEntered = double.parse(_cashController.text.trim());
      final double debtPaidEntered =
          double.tryParse(_debtPaidController.text.trim()) ?? 0.0;

      if (cashEntered > _totalExpectedValue) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'خطأ: الكاش (${cashEntered.toStringAsFixed(2)}) أكبر من قيمة البضاعة (${_totalExpectedValue.toStringAsFixed(2)}).',
            ),
            backgroundColor: Colors.orange,
          ),
        );
        return;
      } else if (cashEntered < _totalExpectedValue) {
        final double difference = _totalExpectedValue - cashEntered;
        final bool confirmDebt = await _showDebtConfirmationDialog(difference);
        if (!confirmDebt) return;
      }

      await _performSubmit(
        cashEntered,
        debtPaidEntered,
        _notesController.text.trim().isNotEmpty
            ? _notesController.text.trim()
            : null,
      );
    } else if (_selectedOutcome == 'NoSale') {
      final double debtPaidEntered =
          double.tryParse(_debtPaidController.text.trim()) ?? 0.0;
      final String? notesOrReason =
          _notesController.text.trim().isNotEmpty
              ? _notesController.text.trim()
              : null;
      if (debtPaidEntered < 0) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('مبلغ تحصيل الذمة لا يمكن أن يكون سالباً.'),
            backgroundColor: Colors.orange,
          ),
        );
        return;
      }
      await _performSubmit(0.0, debtPaidEntered, notesOrReason);
    } else if (_selectedOutcome == 'Postponed') {
      final String? notesOrReason =
          _notesController.text.trim().isNotEmpty
              ? _notesController.text.trim()
              : null;
      if (notesOrReason == null || notesOrReason.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('الرجاء إدخال سبب التأجيل أو ملاحظة للمتابعة.'),
            backgroundColor: Colors.orange,
          ),
        );
        return;
      }
      await _performSubmit(0.0, 0.0, notesOrReason);
    }
  }

  // --- دالة الإرسال الفعلية للـ API (بصيغة السلة الجديدة) ---
  Future<void> _performSubmit(
    double cashCollected,
    double debtPaid,
    String? notes,
  ) async {
    setState(() {
      _isSubmitting = true;
    });

    // بناء سلة المشتريات (تتضمن كراتين، حبات، وعينات)
    List<Map<String, dynamic>> cartItems = [];
    int totalCartons = 0;

    _cartQuantities.forEach((id, qtyMap) {
      int cartons = qtyMap['cartons'] ?? 0;
      int packs = qtyMap['packs'] ?? 0;
      int sampleCartons = qtyMap['sample_cartons'] ?? 0;
      int samplePacks = qtyMap['sample_packs'] ?? 0;

      if (cartons > 0 || packs > 0 || sampleCartons > 0 || samplePacks > 0) {
        cartItems.add({
          'product_variant_id': id,
          'quantity': cartons,
          'packs': packs,
          'sample_cartons': sampleCartons, // +++ إرسال العينات +++
          'sample_packs': samplePacks, // +++ إرسال العينات +++
        });
        totalCartons += cartons;
      }
    });

    Map<String, dynamic> payload = {
      'outcome': _selectedOutcome!,
      'cash_collected': cashCollected,
      'debt_paid': debtPaid,
      'notes': notes,
    };

    if (_selectedOutcome == 'Sale') {
      payload['cart_items'] = cartItems;
      payload['returns'] = _returnsList; // +++ إرسال التوالف +++
      payload['total_quantity_sold'] = totalCartons; // كمعلومة إضافية للباك إند
    } else if (_selectedOutcome == 'NoSale') {
      payload['no_sale_reason'] = notes;
    }

    final url = Uri.parse(
      'http://10.0.2.2:5000/visits/${widget.visitId}',
    ); // استخدم IP جهازك

    try {
      Map<String, String> headers = await getAuthenticatedHeaders(
        needsContentType: false,
      );
      headers = {...headers, 'Content-Type': 'application/json; charset=UTF-8'};

      final response = await http
          .put(url, headers: headers, body: jsonEncode(payload))
          .timeout(const Duration(seconds: 20));

      if (!mounted) return;

      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('تم حفظ نتيجة الزيارة بنجاح!'),
            backgroundColor: Colors.green,
          ),
        );
        Navigator.pop(context, true);
      } else if (response.statusCode == 401) {
        await handleUnauthorized(context);
      } else {
        String errorMessage = 'فشل حفظ الزيارة (رمز: ${response.statusCode})';
        try {
          final errorData = jsonDecode(response.body);
          if (errorData is Map && errorData.containsKey('message')) {
            errorMessage = errorData['message'];
          }
        } catch (_) {}
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('خطأ: $errorMessage'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } catch (error) {
      if (!mounted) return;
      String errorMsg = 'حدث خطأ في الاتصال بالخادم.';

      if (error is TimeoutException) {
        errorMsg = 'انتهت مهلة الاتصال بالخادم.';
      } else if (error is SocketException) {
        errorMsg = 'خطأ في الشبكة، تأكد من اتصالك بالإنترنت.';
      } else {
        errorMsg = error.toString().replaceFirst("Exception: ", "");
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(errorMsg), backgroundColor: Colors.red),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

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
          mapType:
              MapType.google, // يمكنك تحديد نوع الخريطة المفضل أو تركه تلقائياً
          coords: Coords(lat, lng),
          title: title,
          description: description ?? '',
        );
      } else if (link != null && link.trim().isNotEmpty) {
        developer.log(
          'Coordinates not found, attempting to launch manual link: $link',
        );
        final Uri url = Uri.parse(link.trim());

        // استخدام launchUrl مباشرة، سيعيد false إذا فشل
        if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
          developer.log('Could not launch URL: $link');
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text('لا يمكن فتح الرابط: $link'),
                backgroundColor: Colors.red,
              ),
            );
          }
        }
      } else {
        developer.log('No location data available (coordinates or link).');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('لا تتوفر بيانات موقع لهذا المحل.'),
              backgroundColor: Colors.orange,
            ),
          );
        }
      }
    } catch (e, s) {
      developer.log('Error opening map/link: $e', error: e, stackTrace: s);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('حدث خطأ عند محاولة عرض الموقع: ${e.toString()}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      // if (mounted) setState(() { /* إعادة تعيين متغير الحالة إذا أضفته */ });
    }
  }
  // --- نهاية دالة فتح الخريطة ---

  // --- نافذة التوالف والعينات (Bottom Sheet) ---
  void _showExtraOptionsSheet(
    int variantId,
    String productName,
    int maxSamples,
  ) {
    int sampleCartons = _cartQuantities[variantId]?['sample_cartons'] ?? 0;
    int samplePacks = _cartQuantities[variantId]?['sample_packs'] ?? 0;

    int returnCartons = 0;
    int returnPacks = 0;
    String returnType = 'Factory_Defect';
    final returnReasonController = TextEditingController();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (BuildContext context, StateSetter setModalState) {
            return Padding(
              padding: EdgeInsets.only(
                bottom: MediaQuery.of(ctx).viewInsets.bottom,
                left: 16,
                right: 16,
                top: 16,
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'خيارات إضافية: $productName',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const Divider(height: 30),

                    // --- قسم العينات ---
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.purple.shade50,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.purple.shade200),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text(
                                '🎁 صرف عينات مجانية:',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: Colors.purple,
                                ),
                              ),
                              Text(
                                'السقف المسموح: $maxSamples',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: Colors.purple.shade700,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                            children: [
                              _buildCompactCounter(
                                'كرتونة',
                                '📦',
                                sampleCartons,
                                () => setModalState(() => sampleCartons--),
                                () => setModalState(() => sampleCartons++),
                                () {},
                              ),
                              _buildCompactCounter(
                                'حبة',
                                '🍬',
                                samplePacks,
                                () => setModalState(() => samplePacks--),
                                () => setModalState(() => samplePacks++),
                                () {},
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 15),

                    // --- قسم التوالف والمرتجعات ---
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.shade50,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.red.shade200),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            '♻️ استلام توالف وتبديلها:',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: Colors.red,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                            children: [
                              _buildCompactCounter(
                                'كرتونة',
                                '📦',
                                returnCartons,
                                () => setModalState(() => returnCartons--),
                                () => setModalState(() => returnCartons++),
                                () {},
                              ),
                              _buildCompactCounter(
                                'حبة',
                                '🍬',
                                returnPacks,
                                () => setModalState(() => returnPacks--),
                                () => setModalState(() => returnPacks++),
                                () {},
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          DropdownButtonFormField<String>(
                            value: returnType,
                            decoration: const InputDecoration(
                              labelText: 'سبب التلف',
                              border: OutlineInputBorder(),
                              isDense: true,
                            ),
                            items: const [
                              DropdownMenuItem(
                                value: 'Factory_Defect',
                                child: Text('تالف مصنع (منفس/فاقع)'),
                              ),
                              DropdownMenuItem(
                                value: 'Expired',
                                child: Text('تالف شركة (انتهاء صلاحية)'),
                              ),
                            ],
                            onChanged:
                                (val) => setModalState(() => returnType = val!),
                          ),
                          const SizedBox(height: 10),
                          TextField(
                            controller: returnReasonController,
                            decoration: const InputDecoration(
                              labelText: 'ملاحظات (اختياري)',
                              border: OutlineInputBorder(),
                              isDense: true,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 20),

                    // --- زر الحفظ ---
                    ElevatedButton(
                      onPressed: () {
                        // 1. حفظ العينات
                        setState(() {
                          _cartQuantities[variantId] ??= {
                            'cartons': 0,
                            'packs': 0,
                          };
                          _cartQuantities[variantId]!['sample_cartons'] =
                              sampleCartons;
                          _cartQuantities[variantId]!['sample_packs'] =
                              samplePacks;
                        });

                        // 2. حفظ التوالف
                        if (returnCartons > 0 || returnPacks > 0) {
                          setState(() {
                            _returnsList.add({
                              'product_variant_id': variantId,
                              'cartons': returnCartons,
                              'packs': returnPacks,
                              'return_type': returnType,
                              'reason': returnReasonController.text.trim(),
                            });
                          });
                        }
                        Navigator.pop(context);
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('تم إدراج الإضافات بنجاح'),
                            backgroundColor: Colors.green,
                          ),
                        );
                      },
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      child: const Text('اعتماد التعديلات'),
                    ),
                    const SizedBox(height: 10),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }
} // نهاية كلاس _VisitScreenState
