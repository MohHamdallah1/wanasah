// --- الاستيرادات الأساسية ---
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'dart:developer' as developer;
import 'dart:async';
import 'package:map_launcher/map_launcher.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dio/dio.dart'; // +++ للتعامل مع رفض السيرفر الفوري +++
import '../core/network/api_client.dart'; // +++ للاتصال الأساسي +++
import 'dart:convert'; // +++ الكيّ الجراحي: لفك تشفير الخزنة السرية +++
import '../core/db/local_database.dart';
import '../repositories/sync_repository.dart';

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
  bool _isOnBreak = false; // إضافة هذا السطر لتعريف حالة الاستراحة
  bool _hasChanges = false; // +++ متغير يراقب أي لمسة من المندوب للشاشة +++
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
      _hasChanges = true;
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

  // --- دالة تنظيم جلب البيانات (هجينة: Network-First then Offline-Fallback) ---
  Future<void> _fetchDataOnInit() async {
    if (!mounted) return;
    setState(() {
      _isLoading = true;
      _error = null;
      _fetchProductsError = null;
    });

    try {
      const storage = FlutterSecureStorage();
      String? authStr = await storage.read(key: 'is_authorized');
      String? breakStr = await storage.read(key: 'is_on_break');
      setState(() {
        _isAuthorizedToSell = (authStr == 'true');
        _isOnBreak = (breakStr == 'true');
      });

      await _fetchProductVariantsHybrid();

      if (mounted && _fetchProductsError == null) {
        await _loadVisitDetailsHybrid();
      } else if (mounted && _fetchProductsError != null) {
        setState(() => _error = _fetchProductsError);
      }
    } catch (e) {
      if (mounted) setState(() => _error = 'خطأ غير متوقع.');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  // --- جلب المنتجات (نقرأ من القاعدة المحلية دائماً لأنها مصدر الحقيقة للمخزون) ---
  Future<void> _fetchProductVariantsHybrid() async {
    developer.log(
      'Fetching products from local DB (Single Source of Truth)...',
    );
    try {
      // +++ الكيّ الجراحي: قراءة المنتجات ومخزونها من SQLite مباشرة بدلاً من السيرفر +++
      // السيرفر (/product_variants) لا يرسل كميات المخزون. محرك المزامنة هو المسؤول عن تحديث القاعدة المحلية.
      final localProducts = await LocalDatabase.instance.getProducts();

      if (localProducts.isNotEmpty) {
        setState(() {
          _productVariants = List<Map<String, dynamic>>.from(localProducts);
          _isFetchingProducts = false;
        });
      } else {
        setState(() {
          _fetchProductsError =
              'لا توجد منتجات في سيارتك. تأكد من استلام بضاعة من الإدارة.';
          _isFetchingProducts = false;
        });
      }
    } catch (localErr) {
      setState(() {
        _fetchProductsError = 'فشل قراءة المنتجات المحلية.';
        _isFetchingProducts = false;
      });
    }
  }

  // --- جلب تفاصيل الزيارة (أونلاين للمسودات والخريطة، وإن فشل نقرأ الخزنة) ---
  Future<void> _loadVisitDetailsHybrid() async {
    try {
      final response = await ApiClient.instance.get(
        '/visits/${widget.visitId}',
      ); // تم تصحيح المسار ليتطابق مع السيرفر
      final visitData = response.data;

      setState(() {
        _selectedOutcome = visitData['outcome'];
        _cartQuantities.clear();
        _returnsList.clear();

        if (visitData['cart_items'] != null) {
          for (var item in visitData['cart_items']) {
            _cartQuantities[item['product_variant_id']] = {
              'cartons': item['quantity'] ?? 0,
              'packs': item['packs_quantity'] ?? 0,
              'sample_cartons': item['sample_quantity'] ?? 0,
              'sample_packs': item['sample_packs_quantity'] ?? 0,
            };
          }
        }

        if (visitData['returns'] != null) {
          for (var ret in visitData['returns']) {
            _returnsList.add({
              'product_variant_id': ret['product_variant_id'],
              'cartons': ret['quantity'] ?? 0,
              'packs': ret['packs_quantity'] ?? 0,
              'return_type': ret['return_type'],
              'reason': ret['reason'] ?? '',
            });
          }
        }

        final cashDouble =
            (visitData['cash_collected'] as num?)?.toDouble() ?? 0.0;
        _cashController.text =
            (cashDouble == 0.0) ? '' : cashDouble.toStringAsFixed(2);
        final debtDouble = (visitData['debt_paid'] as num?)?.toDouble() ?? 0.0;
        _debtPaidController.text =
            (debtDouble == 0.0) ? '' : debtDouble.toStringAsFixed(2);
        _notesController.text =
            (visitData['notes'] ?? visitData['no_sale_reason'] ?? '');

        final shopData = visitData['shop'];
        if (shopData is Map) {
          _shopLatitude = (shopData['latitude'] as num?)?.toDouble();
          _shopLongitude = (shopData['longitude'] as num?)?.toDouble();
          _shopLink = shopData['location_link'] as String?;
          _shopAddr = shopData['address'] as String?;
        }

        _calculateLiveTotals();
      });
    } catch (e) {
      developer.log(
        'Network failed for visit details, loading local fallback...',
      );
      try {
        final localVisits = await LocalDatabase.instance.getVisits();
        final visitData = localVisits.firstWhere(
          (v) => (v['visit_id'] ?? v['id']) == widget.visitId,
          orElse: () => {},
        );

        if (visitData.isNotEmpty) {
          // +++ الكيّ الجراحي المعماري: نبش الخزنة (pending_sync) لعرض الفاتورة التي سجلها المندوب +++
          final pendingSyncs = await LocalDatabase.instance.getPendingSyncs();
          Map<String, dynamic>? offlinePayload;

          for (var p in pendingSyncs.reversed) {
            if (p['type'] == 'submit_sale') {
              final payload = jsonDecode(p['payload'] as String);
              if (payload['visitId'] == widget.visitId) {
                offlinePayload = payload;
                break;
              }
            }
          }

          setState(() {
            _cartQuantities.clear();
            _returnsList.clear();
            _shopLatitude = null;
            _shopLongitude = null;
            _shopLink = null;
            _shopAddr = null;

            if (offlinePayload != null) {
              // استعادة بيانات الخزنة لتظهر للمندوب كاملة
              _selectedOutcome = offlinePayload['outcome'];

              if (offlinePayload['cart_items'] != null) {
                for (var item in offlinePayload['cart_items']) {
                  _cartQuantities[item['product_variant_id']] = {
                    'cartons': item['quantity'] ?? 0,
                    'packs': item['packs'] ?? item['packs_quantity'] ?? 0,
                    'sample_cartons':
                        item['sample_cartons'] ?? item['sample_quantity'] ?? 0,
                    'sample_packs':
                        item['sample_packs'] ??
                        item['sample_packs_quantity'] ??
                        0,
                  };
                }
              }
              if (offlinePayload['returns'] != null) {
                for (var ret in offlinePayload['returns']) {
                  _returnsList.add(ret);
                }
              }
              final cashDouble =
                  (offlinePayload['cash_collected'] as num?)?.toDouble() ?? 0.0;
              _cashController.text =
                  (cashDouble == 0.0) ? '' : cashDouble.toStringAsFixed(2);

              final debtDouble =
                  (offlinePayload['debt_paid'] as num?)?.toDouble() ?? 0.0;
              _debtPaidController.text =
                  (debtDouble == 0.0) ? '' : debtDouble.toStringAsFixed(2);

              _notesController.text =
                  offlinePayload['notes'] ??
                  offlinePayload['no_sale_reason'] ??
                  '';
            } else {
              _selectedOutcome =
                  (visitData['outcome'] == 'None' ||
                          visitData['outcome'] == null)
                      ? null
                      : visitData['outcome'];

              // +++ الكيّ الجراحي للكارثة: إذا كانت الزيارة مكتملة ولا يوجد لها أثر في الخزنة، فهذا يعني أنها رُفعت للسيرفر بنجاح +++
              if (_selectedOutcome == 'Sale' ||
                  _selectedOutcome == 'No Sale' ||
                  visitData['status'] == 'Completed') {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'تمت مزامنة هذه الزيارة مع الإدارة مسبقاً. لا يمكن عرض تفاصيلها أو تعديلها أوفلاين.',
                      ),
                      backgroundColor: Colors.orange,
                      duration: Duration(seconds: 4),
                    ),
                  );
                  Navigator.pop(
                    context,
                  ); // إخراج المندوب فوراً لمنع التخريب أو التصفير
                  return;
                }
              }
            }
            _calculateLiveTotals();
          });

          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'أنت أوفلاين: تم استرجاع مسودتك من الخزنة المحلية.',
                ),
                backgroundColor: Colors.blue,
              ),
            );
          }
        } else {
          setState(
            () => _error = 'لا يوجد اتصال، ولم يتم العثور على الزيارة محلياً.',
          );
        }
      } catch (localErr) {
        setState(() => _error = 'فشل قراءة الزيارة المحلية.');
      }
    }
  }

  // --- دالة بناء الواجهة الرئيسية ---
  // دالة الحماية عند محاولة الرجوع
  Future<bool> _onWillPop() async {
    // +++ اللوجيك الذكي: إذا لم يغير المندوب أي شيء بيده، يخرج بهدوء تام +++
    if (!_hasChanges) {
      return true;
    }

    // إذا اختار نتيجة ولم يحفظ، نظهر له تحذيراً
    final shouldPop = await showDialog<bool>(
      context: context,
      builder:
          (context) => AlertDialog(
            title: const Text('تغييرات غير محفوظة!'),
            content: const Text(
              'لقد قمت بإجراء تغييرات. هل أنت متأكد من رغبتك بالخروج وإلغاء هذه التغييرات؟',
            ),
            actions: [
              TextButton(
                onPressed:
                    () => Navigator.of(context).pop(false), // لا، ابق في الشاشة
                child: const Text(
                  'إلغاء الخروج',
                  style: TextStyle(color: Colors.blue),
                ),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                onPressed: () => Navigator.of(context).pop(true), // نعم، اخرج
                child: const Text('نعم، الغِ التغييرات واخرج'),
              ),
            ],
          ),
    );
    return shouldPop ?? false;
  }

  @override
  Widget build(BuildContext context) {
    // +++ التحديث الحديث في فلاتر: استخدام PopScope بدلاً من WillPopScope +++
    return PopScope(
      canPop: false, // نمنع الخروج التلقائي لكي نتحكم به نحن
      onPopInvokedWithResult: (bool didPop, Object? result) async {
        if (didPop) return; // إذا خرج بالفعل، لا تفعل شيئاً

        final bool shouldPop = await _onWillPop();
        if (shouldPop && context.mounted) {
          Navigator.of(context).pop(); // نخرج يدوياً إذا وافق المستخدم
        }
      },
      child: Scaffold(
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
      ),
    );
  }

  // --- دالة بناء محتوى الفورم ---
  Widget _buildVisitForm() {
    return IgnorePointer(
      ignoring:
          _isOnBreak, // +++ هذا السطر يشل حركة الشاشة بالكامل وقت الاستراحة +++
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'الذمة الحالية: ${widget.shopBalance.toStringAsFixed(2)} د.أ',
            ), // استخدام widget للذمة الممررة
            const Divider(height: 30),

            // +++ قفل الشاشة الصارم (الاستراحة أولاً، ثم الصلاحية) +++
            _isOnBreak
                ? Container(
                  margin: const EdgeInsets.symmetric(vertical: 10),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red[50],
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.red),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.coffee, color: Colors.red[800]),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'أنت الآن في وقت الاستراحة. تم إقفال العمليات، يرجى إنهاء الاستراحة لمتابعة البيع.',
                          style: TextStyle(
                            color: Colors.red[800],
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ),
                )
                : _isAuthorizedToSell
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
            if (_selectedOutcome != null && _isAuthorizedToSell && !_isOnBreak)
              const SizedBox(height: 30),
            if (_selectedOutcome != null && _isAuthorizedToSell && !_isOnBreak)
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
      ),
    );
  }

  // --- دالة بناء الأجزاء الشرطية (الجديدة كلياً) ---
  Widget _buildConditionalFields() {
    // +++ شل حركة الحقول تماماً وقت الاستراحة لمنع إحباط المندوب (Frontend Lock) +++
    return IgnorePointer(ignoring: _isOnBreak, child: _buildOutcomeContent());
  }

  Widget _buildOutcomeContent() {
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
                if (value == null || value.trim().isEmpty) return null;
                final parsedValue = double.tryParse(value.trim());
                if (parsedValue == null) return 'الرجاء إدخال مبلغ صحيح';
                if (parsedValue < 0) return 'المبلغ لا يمكن أن يكون سالباً';
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
            validator: (value) {
              if (value == null || value.trim().isEmpty) return null;
              final parsedValue = double.tryParse(value.trim());
              if (parsedValue == null) return 'الرجاء إدخال مبلغ صحيح';
              if (parsedValue < 0) return 'المبلغ لا يمكن أن يكون سالباً';
              return null;
            },
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
        // +++ الكيّ الجراحي: توحيد قراءة الاسم بين السيرفر (variant_name) والمحلي (name) +++
        final String name =
            variant['name'] ?? variant['variant_name'] ?? 'غير معروف';
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
                    (newVal) => _updateCartItem(
                      id,
                      cartons: newVal,
                    ), // +++ إدخال مباشر +++
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
                    (newVal) => _updateCartItem(
                      id,
                      packs: newVal,
                    ), // +++ إدخال مباشر للحبات +++
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }

  // --- ويدجت العداد المصغر (نسخة الإدخال المباشر بدون نوافذ) ---
  Widget _buildCompactCounter(
    String label,
    String emoji,
    int qty,
    VoidCallback onMinus,
    VoidCallback onPlus,
    Function(int) onDirectInput, // +++ تمرير دالة بدلاً من مجرد ضغطة +++
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
            // +++ حقل إدخال مباشر (Inline Editable Text) يفتح الكيبورد فوراً +++
            SizedBox(
              width: 45,
              child: TextFormField(
                key: ValueKey(
                  qty.toString() + label,
                ), // لإجبار التحديث عند النقر على الأزرار
                initialValue: qty > 0 ? '$qty' : '',
                keyboardType: TextInputType.number,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: hasQty ? Colors.green.shade700 : Colors.black87,
                ),
                decoration: const InputDecoration(
                  hintText: '0',
                  border: InputBorder.none,
                  isDense: true,
                  contentPadding: EdgeInsets.zero,
                ),
                onFieldSubmitted: (val) {
                  final int? parsed = int.tryParse(val.trim());
                  onDirectInput(parsed ?? 0);
                },
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
          label: const Text('البيع'),
          selected: _selectedOutcome == 'Sale',
          onSelected: (selected) {
            if (selected) {
              setState(() {
                _hasChanges = true;
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
          label: const Text('رفض'),
          selected: _selectedOutcome == 'NoSale',
          onSelected: (selected) {
            if (selected) {
              setState(() {
                _hasChanges = true;
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
          label: const Text('تأجيل'),
          selected: _selectedOutcome == 'Postponed',
          onSelected: (selected) {
            if (selected) {
              setState(() {
                _hasChanges = true;
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

    // +++ الدرع الفولاذي الموحد لتحصيل الذمم (أونلاين وأوفلاين / بيع وعدم بيع) +++
    final double globalDebtPaid =
        double.tryParse(_debtPaidController.text.trim()) ?? 0.0;
    if (globalDebtPaid > 0) {
      // نقرأ الرصيد الحي من SQLite لضمان الدقة المطلقة وعدم التلاعب في الأوفلاين
      final localVisits = await LocalDatabase.instance.getVisits();
      final visitData = localVisits.firstWhere(
        (v) => (v['visit_id'] ?? v['id']) == widget.visitId,
        orElse: () => {},
      );
      final double realShopBalance =
          (visitData['shop_balance'] ?? widget.shopBalance as num).toDouble();

      if (realShopBalance <= 0) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'مرفوض: هذا المحل ليس عليه ذمم سابقة لتسديدها (الرصيد الحالي: 0.0).',
              ),
              backgroundColor: Colors.red,
              duration: const Duration(seconds: 4),
            ),
          );
        }
        return; // إيقاف العملية فوراً
      }

      if (globalDebtPaid > realShopBalance) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'مرفوض: المبلغ المدخل ($globalDebtPaid) أكبر من إجمالي ذمة المحل (${realShopBalance.toStringAsFixed(2)}).',
              ),
              backgroundColor: Colors.red,
              duration: const Duration(seconds: 4),
            ),
          );
        }
        return; // إيقاف العملية فوراً
      }
    }
    // +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

    if (!mounted) {
      return; // +++ حارس أمني يعالج أخطاء use_build_context_synchronously +++
    }

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

      // +++ الكيّ الجراحي: الحماية من المبيعات الوهمية (Offline Inventory Check) +++
      for (var entry in _cartQuantities.entries) {
        final variantId = entry.key;
        final qtyMap = entry.value;
        final variant = _productVariants.firstWhere(
          (v) => v['id'] == variantId,
          orElse: () => {},
        );

        if (variant.isNotEmpty) {
          int requestedCartons =
              (qtyMap['cartons'] ?? 0) + (qtyMap['sample_cartons'] ?? 0);
          int requestedPacks =
              (qtyMap['packs'] ?? 0) + (qtyMap['sample_packs'] ?? 0);

          int availableCartons = variant['current_cartons'] ?? 0;
          int availablePacks = variant['current_packs'] ?? 0;
          int packsPerCarton = variant['packs_per_carton'] ?? 1;

          int totalRequestedPacks =
              (requestedCartons * packsPerCarton) + requestedPacks;
          int totalAvailablePacks =
              (availableCartons * packsPerCarton) + availablePacks;

          if (totalRequestedPacks > totalAvailablePacks) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  'خطأ: كمية (${variant['variant_name']}) المطلوبة تتجاوز مخزونك الحالي! المتاح: $availableCartons كرتونة و $availablePacks حبة.',
                ),
                backgroundColor: Colors.red,
              ),
            );
            return; // إيقاف البيعة فوراً
          }
        }
      }
      // ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

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

        // +++ الكيّ الجراحي: تطبيق قاعدة السقف الأوفلاين والأونلاين +++
        final localVisits = await LocalDatabase.instance.getVisits();
        final visitData = localVisits.firstWhere(
          (v) => (v['visit_id'] ?? v['id']) == widget.visitId,
          orElse: () => {},
        );
        final double maxDebtLimit =
            (visitData['max_debt_limit'] as num?)?.toDouble() ?? 0.0;

        final double expectedNewTotalDebt = widget.shopBalance + difference;

        // +++ إصلاح الثغرة: إزالة (maxDebtLimit > 0) لأن السقف 0 يعني ممنوع الدين نهائياً +++
        if (expectedNewTotalDebt > maxDebtLimit) {
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'مرفوض: الدين الجديد (${expectedNewTotalDebt.toStringAsFixed(2)}) يتجاوز سقف المحل (${maxDebtLimit.toStringAsFixed(2)} ).',
              ),
              backgroundColor: Colors.red,
              duration: const Duration(seconds: 5),
            ),
          );
          return; // منع البيعة فوراً
        }

        final bool confirmDebt = await _showDebtConfirmationDialog(difference);
        if (!mounted) return;
        if (!confirmDebt) return;
      }
      // +++ الدرع الفولاذي: حماية النطاق الجغرافي (Zone Protection) أوفلاين وأونلاين +++
      final localVisits = await LocalDatabase.instance.getVisits();
      final visitData = localVisits.firstWhere(
        (v) => (v['visit_id'] ?? v['id']) == widget.visitId,
        orElse: () => {},
      );

      final int? shopZone = visitData['shop_zone_id'];
      final int? allowedZone = visitData['allowed_zone_id'];
      final bool isEmergency =
          (visitData['is_emergency'] == 1 || visitData['is_emergency'] == true);

      // القاعدة: إذا كان المحل خارج منطقة المندوب، وليس طلب طوارئ -> ارفض البيع
      if (!isEmergency &&
          shopZone != null &&
          allowedZone != null &&
          shopZone != allowedZone) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'مرفوض: هذا المحل خارج نطاق منطقتك الجغرافية المسموحة اليوم.',
              ),
              backgroundColor: Colors.red,
              duration: Duration(seconds: 5),
            ),
          );
        }
        return; // منع الحفظ فوراً
      }
      // +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

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

  // --- دالة حفظ الفاتورة (هجينة: أونلاين أولاً، ثم أوفلاين) ---
  Future<void> _performSubmit(
    double cashCollected,
    double debtPaid,
    String? notes,
  ) async {
    setState(() {
      _isSubmitting = true;
    });

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
          'sample_cartons': sampleCartons,
          'sample_packs': samplePacks,
        });
        totalCartons += cartons;
      }
    });

    Map<String, dynamic> payload = {
      'visitId': widget.visitId,
      'outcome': _selectedOutcome!,
      'cash_collected': cashCollected,
      'debt_paid': debtPaid,
      'notes': notes,
    };

    if (_selectedOutcome == 'Sale') {
      payload['cart_items'] = cartItems;
      payload['returns'] = _returnsList;
      payload['total_quantity_sold'] = totalCartons;
    } else if (_selectedOutcome == 'NoSale') {
      payload['no_sale_reason'] = notes;
    }

    try {
      // +++ المحاولة الهجينة (Online First) من خلال محرك المزامنة +++
      // العقل المدبر الآن يتولى العملية بالكامل ولا ننتظر منه boolean
      await SyncRepository().saveInvoice(
        visitId: widget.visitId,
        payload: payload,
      );

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم حفظ العملية بنجاح.'),
          backgroundColor: Colors.green,
        ),
      );

      Navigator.pop(context, true);
    } on DioException catch (e) {
      // +++ التقاط رفض السيرفر الفوري (401 طرد أو 400 رفض بضاعة) +++
      if (!mounted) return;

      String errorMsg = 'رفض السيرفر العملية.';
      if (e.response?.data != null && e.response?.data is Map) {
        errorMsg = e.response?.data['message'] ?? errorMsg;
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('خطأ من السيرفر: $errorMsg'),
          backgroundColor: Colors.red,
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('حدث خطأ داخلي: $error'),
          backgroundColor: Colors.red,
        ),
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

    // +++ الكيّ الجراحي: جلب التوالف المحفوظة مسبقاً لنفس المنتج إن وجدت +++
    final existingReturns =
        _returnsList
            .where((item) => item['product_variant_id'] == variantId)
            .toList();

    int returnCartons =
        existingReturns.isNotEmpty ? existingReturns.last['cartons'] : 0;
    int returnPacks =
        existingReturns.isNotEmpty ? existingReturns.last['packs'] : 0;
    String returnType =
        existingReturns.isNotEmpty
            ? existingReturns.last['return_type']
            : 'Factory_Defect';
    final returnReasonController = TextEditingController(
      text: existingReturns.isNotEmpty ? existingReturns.last['reason'] : '',
    );

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
                                () => setModalState(() {
                                  if (sampleCartons > 0) sampleCartons--;
                                }),
                                () => setModalState(() => sampleCartons++),
                                (v) => setModalState(
                                  () => sampleCartons = v,
                                ), // +++ إدخال مباشر +++
                              ),
                              _buildCompactCounter(
                                'حبة',
                                '🍬',
                                samplePacks,
                                () => setModalState(() {
                                  if (samplePacks > 0) samplePacks--;
                                }),
                                () => setModalState(() => samplePacks++),
                                (v) => setModalState(
                                  () => samplePacks = v,
                                ), // +++ إدخال مباشر لعينات الحبات +++
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
                                () => setModalState(() {
                                  if (returnCartons > 0) returnCartons--;
                                }),
                                () => setModalState(() => returnCartons++),
                                (v) => setModalState(
                                  () => returnCartons = v,
                                ), // +++ إدخال مباشر لكراتين التوالف +++
                              ),
                              _buildCompactCounter(
                                'حبة',
                                '🍬',
                                returnPacks,
                                () => setModalState(() {
                                  if (returnPacks > 0) returnPacks--;
                                }),
                                () => setModalState(() => returnPacks++),
                                (v) => setModalState(
                                  () => returnPacks = v,
                                ), // +++ إدخال مباشر لحبات التوالف +++
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

                        // 2. حفظ التوالف (تحديث السجل الذكي)
                        setState(() {
                          // +++ مسح التوالف السابقة لنفس المنتج أولاً لتجنب التكرار +++
                          _returnsList.removeWhere(
                            (item) => item['product_variant_id'] == variantId,
                          );

                          // +++ إذا كانت الكمية أكبر من صفر، نقوم بإضافتها للذاكرة +++
                          if (returnCartons > 0 || returnPacks > 0) {
                            _returnsList.add({
                              'product_variant_id': variantId,
                              'cartons': returnCartons,
                              'packs': returnPacks,
                              'return_type': returnType,
                              'reason': returnReasonController.text.trim(),
                            });
                          }
                        });
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
