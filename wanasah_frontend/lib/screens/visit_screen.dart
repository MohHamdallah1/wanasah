import 'package:flutter/material.dart';
import 'dart:async';
import 'package:flutter/services.dart';
import 'package:map_launcher/map_launcher.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:convert';
import '../core/db/local_database.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/visit/visit_bloc.dart';
import '../models/cart_item_model.dart';
import '../models/product_model.dart';

// --- تعريف الكلاس StatefulWidget ---
class VisitScreen extends StatefulWidget {
  final int visitId;
  final String shopName;
  final double shopBalance;
  final String visitStatus;

  const VisitScreen({
    required this.visitId,
    required this.shopName,
    required this.shopBalance,
    required this.visitStatus,
    super.key,
  });

  @override
  State<VisitScreen> createState() => _VisitScreenState();
}

// --- تعريف الكلاس State ---
class _VisitScreenState extends State<VisitScreen> {
  // --- متغيرات الحالة للحقول والـ BLoC ---
  late VisitBloc _visitBloc;
  final _cashController = TextEditingController();
  final _debtPaidController = TextEditingController();
  final _notesController = TextEditingController();

  // متغيرات الحماية (لن يتم مسحها أبداً)
  bool _isOnBreak = false;
  bool _isAuthorizedToSell = false;
  bool _hasChanges = false;
  bool _isLoading = true;
  bool _isSubmitting = false; 
  bool _isCatalogMode = false; // +++ مفتاح التبديل بين الفاتورة والكاتالوج +++
  String? _error;

  // متغيرات الموقع والحماية الجغرافية والمالية
  double? _shopLatitude;
  double? _shopLongitude;
  String? _shopLink;
  String? _shopAddr;
  int? _shopZone;
  int? _allowedZone;
  bool _isEmergency = false;
  double _maxDebtLimit = 0.0;
  // +++ الدرع البصري: متغيرات معلومات الاتصال +++
  String? _shopOwner;
  String? _shopPhone;

  @override
  void initState() {
    super.initState();
    _visitBloc = VisitBloc();

    // +++ النسف المعماري للـ Jank (التداخل): تأخير العمليات الثقيلة حتى ينتهي Navigator Animation +++
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _visitBloc.add(LoadVisitCatalog(widget.shopBalance));
        _fetchDataOnInit();
      }
    });

    _cashController.addListener(() {
      // +++ الكي الجراحي 1: إزالة _hasChanges لمنع ظهور التبويب المزعج بمجرد اللمس، وحماية الحسبة من الفواصل +++
      final amount = double.tryParse(_cashController.text.replaceAll(RegExp(r'[,،]'), '.').trim()) ?? 0.0;
      _visitBloc.add(UpdateCashCollected(amount));
    });

    // +++ ربط حقل تسديد الدين بالعقل المدبر لتحديث الذمة لحظياً +++
    _debtPaidController.addListener(() {
      // +++ تم الحذف هنا أيضاً +++
      final amount = double.tryParse(_debtPaidController.text.replaceAll(RegExp(r'[,،]'), '.').trim()) ?? 0.0;
      _visitBloc.add(UpdateDebtPaid(amount));
    });
  }

  @override
  void dispose() {
    _cashController.dispose();
    _debtPaidController.dispose();
    _notesController.dispose();
    _visitBloc.close();
    super.dispose();
  }

  // --- دالة التهيئة (جلب الحمايات والمسودة) ---
  Future<void> _fetchDataOnInit() async {
    if (!mounted) return;
    setState(() => _isLoading = true);

    try {
      // 1. قراءة الحمايات
      const storage = FlutterSecureStorage();
      String? authStr = await storage.read(key: 'is_authorized');
      String? breakStr = await storage.read(key: 'is_on_break');
      _isAuthorizedToSell = (authStr == 'true');
      _isOnBreak = (breakStr == 'true');

      // 2. قراءة بيانات المحل المحلية للـ Geofencing وسقف الدين
      final localVisits = await LocalDatabase.instance.getVisits();
      final visitData = localVisits.firstWhere(
        (v) => (v['visit_id'] ?? v['id']) == widget.visitId,
        orElse: () => {},
      );

      if (visitData.isNotEmpty) {
        _shopZone = visitData['shop_zone_id'];
        _allowedZone = visitData['allowed_zone_id'];
        _isEmergency =
            (visitData['is_emergency'] == 1 ||
                visitData['is_emergency'] == true);
        // +++ الدرع النوعي (Safe Parse): منع الانهيار إذا كانت القيمة نصية من SQLite +++
        _maxDebtLimit = double.tryParse(visitData['max_debt_limit']?.toString() ?? '0') ?? 0.0;
        _shopLatitude = double.tryParse((visitData['latitude'] ?? visitData['shop_latitude'])?.toString() ?? '');
        _shopLongitude = double.tryParse((visitData['longitude'] ?? visitData['shop_longitude'])?.toString() ?? '');
        // +++ جلب معلومات الاتصال من الداتابيز المحلية +++
        _shopOwner = visitData['shop_owner']?.toString();
        _shopPhone = visitData['shop_phone']?.toString();
        _shopLink =
            visitData['location_link'] ?? visitData['shop_location_link'];
        _shopAddr = visitData['address'];

        // +++ الدرع الفولاذي: إدارة تعديل الزيارات المكتملة بأعلى معايير الـ UX +++
        final String? currentStatus =
            visitData['status'] ?? visitData['visit_status'];

        if (currentStatus == 'Completed') {
          final pendingSyncs = await LocalDatabase.instance.getPendingSyncs();
          bool isOfflineDraft = pendingSyncs.any((p) {
            if (p['type'] == 'submit_sale') {
              final payload = jsonDecode(p['payload'] as String);
              return payload['visitId'] == widget.visitId;
            }
            return false;
          });

          if (!mounted) return;

          // +++ النسف المعماري: السماح بتعديل المسودة الأوفلاين (Local Authority) +++
          if (isOfflineDraft) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'تنبيه: أنت تقوم بتعديل فاتورة لم تُرسل للإدارة بعد (أوفلاين).',
                ),
                backgroundColor: Colors.blue,
                duration: Duration(seconds: 3),
              ),
            );
          }

          // +++ النسف المعماري (متوسط 3): إنذار الكاش المزلزل لمنع السرقة أو نسيان إرجاع المال +++
          final double oldCash = double.tryParse(visitData['cash_collected']?.toString() ?? '0') ?? 0.0;
          final double oldDebt = double.tryParse(visitData['debt_paid']?.toString() ?? '0') ?? 0.0;
          final double totalOldMoney = oldCash + oldDebt;

          if (totalOldMoney > 0) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  '🚨 تحذير مالي خطير: هذه الزيارة محصلة مسبقاً بمبلغ (${totalOldMoney.toStringAsFixed(3)} د.أ). إذا قمت بالحفظ، سيقوم النظام بتصفير هذا المبلغ، ويجب عليك إعادته يدوياً لصاحب المحل فوراً!',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 15,
                    color: Colors.white,
                  ),
                ),
                backgroundColor: Colors.red.shade800,
                duration: const Duration(
                  seconds: 10,
                ), // وقت طويل ليقرأه غصب عنه
              ),
            );
          } else {
            // التحذير العادي لفاتورة بدون كاش
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'تنبيه: هذه الزيارة معتمدة مسبقاً. أي حفظ سيلغي القديمة ويعتمد الجديدة.',
                ),
                backgroundColor: Colors.orange,
                duration: Duration(seconds: 4),
              ),
            );
          }
        }
      }

      // 3. محاولة استرجاع المسودة المالية (Draft) من الخزنة
      final pendingSyncs = await LocalDatabase.instance.getPendingSyncs();
      Map<String, dynamic>? offlinePayload;
      for (var p in pendingSyncs.reversed) {
        if (p['type'] == 'submit_sale') {
          final payload = jsonDecode(p['payload'] as String);
          // +++ إصلاح مشكلة عدم تزامن الفاتورة: الفحص المزدوج لاسم المفتاح في الـ JSON +++
          if (payload['visitId'] == widget.visitId || payload['visit_id'] == widget.visitId) {
            offlinePayload = payload;
            break;
          }
        }
      }

      // +++ النسف المعماري: استخراج الحالة للتحقق من المزامنة العكسية بأمان +++
      final String? currentStatus =
          visitData['status'] ?? visitData['visit_status'];

      if (offlinePayload != null) {
        final cashDouble = double.tryParse(offlinePayload['cash_collected']?.toString() ?? '0') ?? 0.0;
        _cashController.text = (cashDouble == 0.0) ? '' : cashDouble.toStringAsFixed(3);
        final debtDouble = double.tryParse(offlinePayload['debt_paid']?.toString() ?? '0') ?? 0.0;
        _debtPaidController.text =
            (debtDouble == 0.0) ? '' : debtDouble.toStringAsFixed(3);
        _notesController.text =
            offlinePayload['notes'] ?? offlinePayload['no_sale_reason'] ?? '';

        // +++ النسف المعماري (حرج 5): استرجاع السلة والتوالف من الخزنة السرية إذا كانت الزيارة أوفلاين +++
        if (offlinePayload['cart_items'] != null ||
            offlinePayload['returns'] != null) {
          
          // +++ الكي الجراحي الأضخم: إجبار الكود على الانتظار حتى يجهز البلوك (VisitReady) قبل حقن الفاتورة +++
          // +++ درع التعليق اللانهائي: الخروج من الانتظار إذا نجح التحميل أو فشل لمنع تجميد التطبيق +++
          if (_visitBloc.state is! VisitReady) {
            await _visitBloc.stream.firstWhere(
              (state) => state is VisitReady || state is VisitError,
              orElse: () => VisitLoading(),
            );
            if (_visitBloc.state is! VisitReady) return;
          }

          _visitBloc.add(
            LoadCompletedVisitData(
              cartItemsJson:
                  offlinePayload['cart_items'] != null
                      ? jsonEncode(offlinePayload['cart_items'])
                      : null,
              returnsJson:
                  offlinePayload['returns'] != null
                      ? jsonEncode(offlinePayload['returns'])
                      : null,
              cashCollected: cashDouble,
              debtPaid: debtDouble,
              notes: _notesController.text,
            ),
          );
        }

        if (mounted) {
          _cashController.text = cashDouble > 0 ? cashDouble.toStringAsFixed(3) : '';
          _debtPaidController.text = debtDouble > 0 ? debtDouble.toStringAsFixed(3) : '';
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('تم استرجاع الكاش والملاحظات من المسودة.'),
              backgroundColor: Colors.blue,
            ),
          );
        }
      } else if (currentStatus == 'Completed') {
        final String? cartJson = visitData['cart_items'];
        final String? returnsJson = visitData['returns'];
        final double oldCash = double.tryParse(visitData['cash_collected']?.toString() ?? '0') ?? 0.0;
        final double oldDebt = double.tryParse(visitData['debt_paid']?.toString() ?? '0') ?? 0.0;

        if (cartJson != null || returnsJson != null) {
          
          // +++ حماية التزامن: الانتظار حتى يجهز البلوك لاستقبال الفاتورة القديمة +++
          // +++ درع التعليق اللانهائي: الخروج من الانتظار إذا نجح التحميل أو فشل لمنع تجميد التطبيق +++
          if (_visitBloc.state is! VisitReady) {
            await _visitBloc.stream.firstWhere(
              (state) => state is VisitReady || state is VisitError,
              orElse: () => VisitLoading(),
            );
            if (_visitBloc.state is! VisitReady) return;
          }

          _visitBloc.add(
            LoadCompletedVisitData(
              cartItemsJson: cartJson,
              returnsJson: returnsJson,
              cashCollected: oldCash,
              debtPaid: oldDebt,
              notes: visitData['notes'] ?? '',
            ),
          );
          if (mounted) {
            _cashController.text = oldCash > 0 ? oldCash.toStringAsFixed(3) : '';
            _debtPaidController.text = oldDebt > 0 ? oldDebt.toStringAsFixed(3) : '';
          }
        }
      }
    } catch (e) {
      _error = 'حدث خطأ أثناء تحميل بيانات الحماية: $e';
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  // --- دالة החماية عند محاولة الرجوع ---
  Future<bool> _onWillPop() async {
    if (!_hasChanges) return true;
    final shouldPop = await showDialog<bool>(
      context: context,
      builder:
          (context) => AlertDialog(
            title: const Text('تغييرات غير محفوظة!'),
            content: const Text(
              'لقد قمت بإجراء تغييرات. هل أنت متأكد من رغبتك بالخروج وإلغاء التغييرات؟',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: const Text(
                  'إلغاء',
                  style: TextStyle(color: Colors.blue),
                ),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                onPressed: () => Navigator.of(context).pop(true),
                child: const Text('نعم، اخرج'),
              ),
            ],
          ),
    );
    return shouldPop ?? false;
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => FocusScope.of(context).unfocus(), // إغلاق الكيبورد عند لمس أي مكان
      child: BlocProvider.value(
      value: _visitBloc,
      child: BlocListener<VisitBloc, VisitState>(
          listener: (context, state) {
            if (state is VisitError) {
              if (mounted) setState(() => _isSubmitting = false);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(state.message), backgroundColor: Colors.red),
              );
            } else if (state is VisitSubmissionSuccess) {
              if (mounted) setState(() => _isSubmitting = false);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('تم حفظ العملية بنجاح.'), backgroundColor: Colors.green),
              );
              Navigator.pop(context, true);
            } else if (state is VisitReady) {
              // +++ النسف المعماري لفخ التجميد (The Deadlock Breaker) +++
              // إذا عاد البلوك لحالة الفاتورة (VisitReady) وكان الزر مقفلاً، نفك القفل فوراً لمنع شلل التطبيق!
              if (_isSubmitting && mounted) {
                setState(() => _isSubmitting = false);
              }
            }
          },
        child: PopScope(
          canPop: false,
          onPopInvokedWithResult: (bool didPop, Object? result) async {
            if (didPop) return;
            if (_isCatalogMode) {
              setState(() => _isCatalogMode = false);
              return;
            }
            final bool shouldPop = await _onWillPop();
            // +++ الكي الجراحي: استخدام context.mounted بشكل صريح وحصري بعد الـ await لمنع خطأ الـ Async Gap +++
            if (!context.mounted) return; 
            if (shouldPop) {
              Navigator.of(context).pop();
            }
          },
          child: Scaffold(
            backgroundColor: Colors.grey.shade50,
            appBar: AppBar(
              backgroundColor: Colors.grey.shade50,
              elevation: 0,
              surfaceTintColor: Colors.transparent,
              leading: IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () {
                  if (_isCatalogMode) {
                    setState(() => _isCatalogMode = false);
                  } else {
                    // +++ الكي الجراحي لـ Bug 2: تفويض الخروج للـ PopScope لمنع تكرار رسالة التأكيد مرتين +++
                    Navigator.maybePop(context);
                  }
                },
              ),
              title: Text(widget.shopName),
              centerTitle: true,
              actions: [
                // +++ ربط الأيقونة الفخمة لفتح معلومات الاتصال +++
                IconButton(
                  icon: const Icon(Icons.contact_phone, color: Colors.teal),
                  onPressed: _showContactBottomSheet,
                ),
                IconButton(
                  icon: const Icon(Icons.map_outlined),
                  tooltip: 'عرض الموقع على الخريطة',
                  onPressed:
                      (_shopLatitude == null &&
                              _shopLongitude == null &&
                              (_shopLink == null || _shopLink!.isEmpty))
                          ? null
                          : _openMap,
                ),
              ],
            ),
            body:
                _isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : _error != null
                    ? Center(
                      child: Text(
                        'خطأ: $_error',
                        style: const TextStyle(color: Colors.red),
                      ),
                    )
                    : _buildSmartCartUI(),
          ),
        ),
      ),
      ),
    );
  }

  // --- واجهة السلة الذكية 2026 (الموحدة) ---
  Widget _buildSmartCartUI() {
    final bool isLocked = _isOnBreak || !_isAuthorizedToSell; // +++ تحديد حالة القفل العام +++

    // +++ الكي الجراحي 2: إزالة IgnorePointer للسماح للمندوب بالتمرير (Scroll) ورؤية الفاتورة حتى لو كان مقفلاً +++
    return BlocBuilder<VisitBloc, VisitState>(
      builder: (context, state) {
        if (state is VisitLoading) return const Center(child: CircularProgressIndicator());
        if (state is VisitReady) {
          if (_isCatalogMode) {
            return Column(
              children: [
                _SearchableCatalog(
                  catalog: state.catalog,
                  cart: state.cart,
                  visitBloc: _visitBloc,
                  onCartUpdated: () => setState(() => _hasChanges = true),
                  onClose: () => setState(() => _isCatalogMode = false),
                ),
              ],
            );
          }

          return Column(
            children: [
              _buildSafetyBanners(),
              Expanded(
                child: state.cart.isEmpty 
                  ? _buildEmptyCartPlaceholder(isLocked) 
                  : _buildInvoiceListView(state.cart, isLocked),
              ),
              // +++ الدرع المعماري (Overflow Fix): إجبار الفوتر على عدم تجاوز مساحة محددة لتجنب الكراش الأصفر والأسود عند ظهور الكيبورد +++
              ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.45, 
                ),
                child: SingleChildScrollView(
                  physics: const ClampingScrollPhysics(),
                  child: _buildFixedFooter(state, isLocked),
                ),
              ),
            ],
          );
        }
        return const SizedBox.shrink();
      },
    );
  }

  // دالة مساعدة لبناء شكل الفاتورة النظيف
  Widget _buildInvoiceListView(List<CartItemModel> cart, bool isLocked) {
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: cart.length + 1,
      itemBuilder: (context, index) {
        if (index == cart.length) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 20),
            child: ElevatedButton.icon(
              // +++ تعطيل الزر إذا كانت الشاشة مقفلة +++
              onPressed: isLocked ? null : () => setState(() => _isCatalogMode = true),
              icon: const Icon(Icons.add_shopping_cart),
              label: const Text('إضافة أصناف أخرى', style: TextStyle(fontWeight: FontWeight.bold)),
              style: ElevatedButton.styleFrom(backgroundColor: isLocked ? Colors.grey.shade200 : Colors.blue.shade50, foregroundColor: isLocked ? Colors.grey : Colors.blue.shade800, padding: const EdgeInsets.all(15)),
            ),
          );
        }
        final item = cart[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 10),
          color: isLocked ? Colors.grey.shade100 : Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15), side: BorderSide(color: Colors.grey.shade200)),
          child: ListTile(
            title: Text(item.name, style: TextStyle(fontWeight: FontWeight.bold, color: isLocked ? Colors.grey : Colors.black)),
            // +++ الكي الجراحي لـ Bug 7: عرض توالف وإكسباير مصنع بدلاً من مصفوفة الـ returns الفارغة +++
            subtitle: Text('المبيع: ${item.cartons}ك | ${item.packs}ح  -  مرتجع/توالف: ${item.returnFactoryCartons + item.returnExpiredCartons}ك | ${item.returnFactoryPacks + item.returnExpiredPacks}ح'),
            trailing: Text('${item.totalSalePrice.toStringAsFixed(3)} د.أ', style: TextStyle(color: isLocked ? Colors.grey : Colors.green, fontWeight: FontWeight.bold)),
            onTap: isLocked ? null : () => setState(() => _isCatalogMode = true), // العودة للكاتالوج للتعديل
          ),
        );
      },
    );
  }

  Widget _buildEmptyCartPlaceholder(bool isLocked) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.shopping_basket_outlined, size: 100, color: Colors.grey.shade300),
          const SizedBox(height: 20),
          const Text('الفاتورة فارغة حالياً', style: TextStyle(fontSize: 18, color: Colors.grey, fontWeight: FontWeight.bold)),
          const SizedBox(height: 30),
          ElevatedButton.icon(
            onPressed: isLocked ? null : () => setState(() => _isCatalogMode = true),
            icon: const Icon(Icons.add, size: 30),
            label: const Text('بدء إضافة المنتجات', style: TextStyle(fontSize: 18)),
            style: ElevatedButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 15), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20))),
          ),
        ],
      ),
    );
  }

  Widget _buildSafetyBanners() {
    return Column(
      children: [
        if (_isOnBreak) Container(width: double.infinity, padding: const EdgeInsets.all(10), color: Colors.red.shade50, child: const Text('⚠️ أنت في استراحة، العمليات مقفلة.', textAlign: TextAlign.center, style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold))),
        if (!_isAuthorizedToSell) Container(width: double.infinity, padding: const EdgeInsets.all(10), color: Colors.orange.shade50, child: const Text('⏳ بانتظار تفعيل خط السير من الإدارة.', textAlign: TextAlign.center, style: TextStyle(color: Colors.orange, fontWeight: FontWeight.bold))),
      ],
    );
  }

  // +++ الدرع البصري (Enterprise UX): نافذة الاتصال السفلية الأنيقة +++
  void _showContactBottomSheet() {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(25)),
      ),
      backgroundColor: Colors.white,
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 50,
                height: 5,
                decoration: BoxDecoration(color: Colors.grey.shade300, borderRadius: BorderRadius.circular(10)),
              ),
              const SizedBox(height: 20),
              const Icon(Icons.storefront, size: 50, color: Colors.teal),
              const SizedBox(height: 10),
              Text(widget.shopName, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              const SizedBox(height: 20),
              ListTile(
                leading: CircleAvatar(backgroundColor: Colors.blue.shade50, child: const Icon(Icons.person, color: Colors.blue)),
                title: const Text('المسؤول / المالك', style: TextStyle(fontSize: 14, color: Colors.grey)),
                subtitle: Text(_shopOwner ?? 'غير مسجل', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.black)),
              ),
              const Divider(),
              ListTile(
                leading: CircleAvatar(backgroundColor: Colors.green.shade50, child: const Icon(Icons.phone, color: Colors.green)),
                title: const Text('رقم التواصل', style: TextStyle(fontSize: 14, color: Colors.grey)),
                subtitle: Text(_shopPhone ?? 'غير مسجل', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.black)),
                trailing: (_shopPhone != null && _shopPhone!.isNotEmpty)
                    ? ElevatedButton.icon(
                        onPressed: () async {
                          // +++ كود الاتصال الفعلي مع حماية الـ Context الصحيحة +++
                          final Uri phoneUri = Uri(scheme: 'tel', path: _shopPhone);
                          if (await canLaunchUrl(phoneUri)) {
                            await launchUrl(phoneUri);
                          } else {
                            // +++ النسف المعماري لخطأ الـ Async Gap: فحص الـ context حصرياً +++
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('تعذر فتح تطبيق الاتصال'), backgroundColor: Colors.red),
                            );
                          }
                        },
                        icon: const Icon(Icons.call, size: 18),
                        label: const Text('اتصال'),
                        style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
                      )
                    : null,
              ),
              const SizedBox(height: 20),
            ],
          ),
        );
      },
    );
  }

  // --- الفوتر الثابت الموحد (مُحصّن ضد الكيبورد والـ UX) ---
  Widget _buildFixedFooter(VisitReady state, bool isLocked) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.1),
            blurRadius: 10,
            spreadRadius: 1,
            offset: const Offset(0, -3),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'إجمالي الفاتورة الصافي:',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              Text(
                '${state.netInvoice.toStringAsFixed(3)} د.أ',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: isLocked ? Colors.grey : Colors.blue,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _cashController,
                  enabled: !isLocked, 
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(
                    labelText: 'الكاش المستلم',
                    labelStyle: TextStyle(color: isLocked ? Colors.grey : Colors.black87),
                    filled: true,
                    fillColor: isLocked ? Colors.grey.shade200 : Colors.white,
                    disabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.grey.shade300)),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.grey.shade300)),
                    focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.blue.shade300, width: 2)),
                    prefixIcon: Icon(Icons.money, color: isLocked ? Colors.grey : Colors.green),
                    suffixIcon: isLocked ? const Icon(Icons.lock, color: Colors.grey, size: 18) : null,
                    isDense: true,
                  ),
                  onChanged: (_) => _hasChanges = true, 
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextField(
                  controller: _debtPaidController,
                  enabled: !isLocked, 
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: InputDecoration(
                    labelText: 'تحصيل ذمة سابقة',
                    labelStyle: TextStyle(color: isLocked ? Colors.grey : Colors.black87),
                    filled: true,
                    fillColor: isLocked ? Colors.grey.shade200 : Colors.white,
                    disabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.grey.shade300)),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.grey.shade300)),
                    focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.orange.shade300, width: 2)),
                    prefixIcon: Icon(Icons.account_balance_wallet, color: isLocked ? Colors.grey : Colors.orange),
                    suffixIcon: isLocked ? const Icon(Icons.lock, color: Colors.grey, size: 18) : null,
                    isDense: true,
                  ),
                  onChanged: (_) => _hasChanges = true,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _notesController,
            enabled: !isLocked, 
            decoration: InputDecoration(
              labelText: 'ملاحظات',
              labelStyle: TextStyle(color: isLocked ? Colors.grey : Colors.black87),
              filled: true,
              fillColor: isLocked ? Colors.grey.shade200 : Colors.white,
              disabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.grey.shade300)),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.grey.shade300)),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.blue.shade300, width: 2)),
              prefixIcon: Icon(Icons.note, color: isLocked ? Colors.grey : Colors.blue),
              suffixIcon: isLocked ? const Icon(Icons.lock, color: Colors.grey, size: 18) : null,
              isDense: true,
            ),
            onChanged: (_) => _hasChanges = true,
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton.icon(
              onPressed: (_isSubmitting || isLocked) ? null : () => _validateAndSubmitSmart(state),
              icon: Icon(isLocked ? Icons.lock_outline : Icons.check_circle_outline, size: 24),
              label: Text(
                widget.visitStatus == 'Completed' ? 'تعديل الفاتورة واعتمادها' : 'إنهاء الزيارة',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: widget.visitStatus == 'Completed' ? Colors.orange[700] : Colors.teal,
                disabledBackgroundColor: Colors.grey.shade300,
                disabledForegroundColor: Colors.grey.shade600,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                elevation: isLocked ? 0 : 3,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // --- دالة فتح الخريطة ---
  Future<void> _openMap() async {
    final double? lat = _shopLatitude;
    final double? lng = _shopLongitude;
    final String? link = _shopLink;
    final String title = widget.shopName;
    final String? description = _shopAddr;

    try {
      if (lat != null && lng != null) {
        await MapLauncher.showMarker(
          mapType: MapType.google,
          coords: Coords(lat, lng),
          title: title,
          description: description ?? '',
        );
      } else if (link != null && link.trim().isNotEmpty) {
        final Uri url = Uri.parse(link.trim());
        if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
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
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('لا تتوفر بيانات موقع لهذا المحل.'),
              backgroundColor: Colors.orange,
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('حدث خطأ عند محاولة عرض الموقع: ${e.toString()}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  // --- دالة الحماية والإنهاء الفولاذية (معمارية البلوك) ---
  Future<void> _validateAndSubmitSmart(VisitReady state) async {
    // +++ درع الـ Double Tap: منع تنفيذ الدالة إذا كانت قيد المعالجة لتجنب إرسال الفاتورة مرتين +++
    if (_isSubmitting) return;

    // 1. حماية الاستراحة والصلاحية
    if (_isOnBreak || !_isAuthorizedToSell) return;

    // +++ الدرع الميداني: إجبار المندوب على سبب العينة قبل إرهاق السيرفر +++
    for (var item in state.cart) {
      if ((item.sampleCartons > 0 || item.samplePacks > 0) &&
          (item.sampleReason.trim().isEmpty)) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('مرفوض: يجب اختيار أو كتابة سبب العينة للمنتج (${item.name}).'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 4),
          ),
        );
        setState(() => _isSubmitting = false); // فك القفل عن الزر ليحاول مجدداً
        return; // إيقاف العملية فوراً
      }
    }

    // +++ الكي الجراحي: درع حماية المخزون من البيع الوهمي +++
    for (var item in state.cart) {
      final int requestedPacks = (item.cartons * item.packsPerCarton) + item.packs + (item.sampleCartons * item.packsPerCarton) + item.samplePacks;
      final int availablePacks = (item.availableCartons * item.packsPerCarton) + item.availablePacks;
      // +++ الكي الجراحي لـ Bug 2: نرفض العملية فقط إذا كان هناك "طلب مبيعات" فعلي يتجاوز الرصيد +++
      if (requestedPacks > 0 && requestedPacks > availablePacks) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('مرفوض: الكمية المطلوبة من (${item.name}) تتجاوز رصيد سيارتك!'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 5),
          ),
        );
        setState(() => _isSubmitting = false);
        return;
      }
    }

    // 2. حماية المنطقة (Geofence)
    if (!_isEmergency &&
        _shopZone != null &&
        _allowedZone != null &&
        _shopZone != _allowedZone) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('مرفوض: المحل خارج منطقتك المسموحة.'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    // 3. التحقق المالي الصارم (Real-Time UI Shield)
    final String rawCashText = _cashController.text.trim();
    final String rawDebtText = _debtPaidController.text.trim();
    
    final double cashEntered = double.tryParse(rawCashText.replaceAll(RegExp(r'[,،]'), '.')) ?? 0.0;
    final double debtPaidEntered = double.tryParse(rawDebtText.replaceAll(RegExp(r'[,،]'), '.')) ?? 0.0;

    // +++ درع الإجبارية (Mandatory Fields): إجبار المندوب على كتابة الرقم حتى لو كان صفراً لمنع الحفظ بالخطأ +++
    if (state.netInvoice > 0 && rawCashText.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('مرفوض: الفاتورة تحتوي على مبيعات، يجب إدخال قيمة في حقل (الكاش المستلم). إذا لم تستلم نقداً، اكتب 0.'),
          backgroundColor: Colors.red,
          duration: Duration(seconds: 4),
        ),
      );
      return;
    }

    // +++ النسف المعماري لثغرة الرصيد الصفري +++
    if (debtPaidEntered > widget.shopBalance) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(widget.shopBalance <= 0 ? 'مرفوض: المحل ليس عليه أي ديون سابقة.' : 'مبلغ السداد أكبر من ذمة المحل!'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    // +++ الكي الجراحي لـ Bug 1: السماح بإدخال الكاش حتى لو الفاتورة مرتجع (سالب) +++
    if (state.netInvoice > 0 && cashEntered > state.netInvoice) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('الكاش المستلم أكبر من قيمة الفاتورة الصافية!'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    // 4. الحماية الفولاذية اللحظية لسقف الدين (بدون الاعتماد على تأخير البلوك)
    final double newInvoiceDebt = state.netInvoice - cashEntered; // ما تبقى من الفاتورة كدين
    final double expectedNewTotalBalance = widget.shopBalance - debtPaidEntered + newInvoiceDebt;

    // +++ الكي الجراحي لـ Bug 5: استخدام هامش التقريب (Epsilon 0.0001) لمنع رفض الفواتير الصحيحة +++
    if ((expectedNewTotalBalance - _maxDebtLimit) > 0.0001) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'مرفوض: سقف الدين لا يسمح!\nالمتبقي من الفاتورة (${newInvoiceDebt.toStringAsFixed(3)}) سيرفع ذمة المحل إلى (${expectedNewTotalBalance.toStringAsFixed(3)}) والسقف هو (${_maxDebtLimit.toStringAsFixed(3)}).',
          ),
          backgroundColor: Colors.red,
          duration: const Duration(seconds: 6), // مدة أطول ليقرأ المندوب التفاصيل
        ),
      );
      return;
    }

    // 5. استنتاج النتيجة الذكي (Smart Outcome)
    String finalOutcome = 'NoSale';
    bool hasSales = state.cart.any((i) => i.cartons > 0 || i.packs > 0);
    // +++ الكي الجراحي لـ Bug 7: قراءة القيم الحقيقية للمرتجعات +++
    bool hasReturns = state.cart.any((i) => i.returnFactoryCartons > 0 || i.returnFactoryPacks > 0 || i.returnExpiredCartons > 0 || i.returnExpiredPacks > 0);
    bool hasSamples = state.cart.any(
      (i) => i.sampleCartons > 0 || i.samplePacks > 0,
    );

    if (hasSales) {
      finalOutcome = 'Sale';
    } else if (hasReturns || hasSamples) {
      // +++ عودة للمنطق التجاري السليم (بيزنس أبو علي): المرتجعات أو العينات بدون مبيعات تعتبر NoSale +++
      finalOutcome = 'NoSale';
    } else if (state.cart.isEmpty) {
      // +++ النسف المعماري (متوسط 4): إجبار המندوب على تقديم مبرر دائماً إذا كانت السلة فارغة، حتى لو سدد ذمة (منع التناقض) +++
      final result = await showDialog<String>(
        context: context,
        builder:
            (context) => AlertDialog(
              title: const Text('إنهاء بدون عمليات؟'),
              content: const Text(
                'لم تقم بإضافة منتجات أو تحصيل كاش. ما السبب؟',
              ),
              actions: [
                TextButton(
                  onPressed: () {
                    // +++ الكيّ الجراحي: حقن السبب آلياً في حقل الملاحظات إذا كان فارغاً لكي يصل للإدارة +++
                    if (_notesController.text.trim().isEmpty) {
                      _notesController.text = 'تأجيل - المحل مغلق';
                    }
                    Navigator.pop(context, 'Postponed');
                  },
                  child: const Text('تأجيل (مغلق مثلاً)'),
                ),
                TextButton(
                  onPressed: () {
                    // +++ حقن سبب عدم البيع آلياً +++
                    if (_notesController.text.trim().isEmpty) {
                      _notesController.text = 'لا يحتاج بضاعة حالياً';
                    }
                    Navigator.pop(context, 'NoSale');
                  },
                  child: const Text('لا يحتاج بضاعة'),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(context, null),
                  child: const Text(
                    'إلغاء',
                    style: TextStyle(color: Colors.red),
                  ),
                ),
              ],
            ),
      );
      if (result == null) return; // المستخدم ألغى
      finalOutcome = result;
    }

    // +++ تفعيل قفل الازدواجية لمنع الـ Double Tap +++
    setState(() => _isSubmitting = true);

    // 6. توجيه الضربة النهائية (إرسال الأمر للمحاسب)
    _visitBloc.add(
      SubmitVisit(
        visitId: widget.visitId,
        outcome: finalOutcome,
        debtPaid: debtPaidEntered,
        notes: _notesController.text.trim(),
      ),
    );

    // +++ الكي الجراحي لـ Bug 1: مؤقت طوارئ لفك قفل الشاشة بعد 10 ثوانٍ في حال فشل الاتصال بصمت +++
    Future.delayed(const Duration(seconds: 10), () {
      if (mounted && _isSubmitting) {
        setState(() => _isSubmitting = false);
      }
    });
  }
} // نهاية كلاس _VisitScreenState

// ============================================================================
// --- كلاسات وحش الـ POS (The 2026 Accordion UI) ---
// تم عزلها في كلاسات منفصلة لضمان الأداء الصاروخي ومنع تداخل الحالات (Jank)
// ============================================================================

class _SearchableCatalog extends StatefulWidget {
  final List<ProductModel> catalog;
  final List<CartItemModel> cart;
  final VisitBloc visitBloc;
  final VoidCallback onCartUpdated;
  final VoidCallback onClose; // +++ أمر الإغلاق الآمن +++

  const _SearchableCatalog({
    required this.catalog,
    required this.cart,
    required this.visitBloc,
    required this.onCartUpdated,
    required this.onClose,
  });

  @override
  State<_SearchableCatalog> createState() => _SearchableCatalogState();
}

class _SearchableCatalogState extends State<_SearchableCatalog> {
  String _searchQuery = '';
  final TextEditingController _searchController = TextEditingController(); // +++ متحكم لتفريغ البحث +++
  // +++ تنظيف الذاكرة: إعدام متغير _drafts الميت +++

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filteredCatalog = widget.catalog.where((p) => p.name.toLowerCase().contains(_searchQuery.toLowerCase())).toList();

    return Expanded( // غلفنا العمود بـ Expanded ليعمل داخل الـ Column الرئيسي
      child: Column(
        children: [
          // سطر البحث (إزالة الإغلاق المكرر والاعتماد على الزر الكبير بالأسفل)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: const BoxDecoration(color: Colors.white, border: Border(bottom: BorderSide(color: Colors.black12))),
            child: Row(
              children: [
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(12)),
                    child: TextField(
                      controller: _searchController,
                      onChanged: (val) => setState(() => _searchQuery = val),
                      decoration: InputDecoration(
                        hintText: 'ابحث عن صنف...',
                        border: InputBorder.none,
                        suffixIcon: _searchQuery.isNotEmpty 
                          ? IconButton(icon: const Icon(Icons.cancel, color: Colors.grey), onPressed: () { _searchController.clear(); setState(() => _searchQuery = ''); }) 
                          : const Icon(Icons.search, color: Colors.blue),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              itemCount: filteredCatalog.length,
              itemBuilder: (context, index) {
                final product = filteredCatalog[index];
                final cartItemIndex = widget.cart.indexWhere((i) => i.productVariantId == product.id);
                final cartItem = cartItemIndex != -1 ? widget.cart[cartItemIndex] : null;

                return _AccordionProductCard(
                  key: ValueKey(product.id), // +++ الكي الجراحي لـ Bug 6: لمنع انتقال الكميات لمنتج آخر عند البحث +++
                  product: product,
                  cartItem: cartItem,
                  isExpanded: true, 
                  // +++ تنظيف الذاكرة +++
                  onToggle: () {}, 
                  visitBloc: widget.visitBloc,
                  onCartUpdated: widget.onCartUpdated,
                );
              },
            ),
          ),
          _buildMasterConfirmButton(),
        ],
      ),
    );
  }

  Widget _buildMasterConfirmButton() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: Colors.white, boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.05), blurRadius: 10, offset: const Offset(0, -5))]),
      child: SizedBox(
        width: double.infinity,
        height: 55,
        child: ElevatedButton(
          onPressed: () {
             HapticFeedback.heavyImpact();
             widget.onClose(); // +++ يغلق الكاتالوج ويعود للفاتورة فقط دون تدمير الزيارة +++
          },
          style: ElevatedButton.styleFrom(backgroundColor: Colors.blue.shade700, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
          child: const Text('اعتماد الكميات والعودة للفاتورة', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
        ),
      ),
    );
  }
}

class _AccordionProductCard extends StatefulWidget {
  final ProductModel product;
  final CartItemModel? cartItem;
  final bool isExpanded;
  final VoidCallback onToggle;
  final VisitBloc visitBloc;
  final VoidCallback onCartUpdated;

  const _AccordionProductCard({
    super.key, // +++ الكي الجراحي: السماح للكلاس باستقبال الـ Key لمنع الخطأ +++
    required this.product,
    required this.cartItem,
    required this.isExpanded,
    required this.onToggle,
    required this.visitBloc,
    required this.onCartUpdated,
  });

  @override
  State<_AccordionProductCard> createState() => _AccordionProductCardState();
}

class _AccordionProductCardState extends State<_AccordionProductCard> {
  final sCartons = TextEditingController();
  final sPacks = TextEditingController();
  
  // +++ العدادات المباشرة للاستبدال +++
  final rfCartons = TextEditingController(); // تالف مصنع
  final rfPacks = TextEditingController();
  final reCartons = TextEditingController(); // إكسباير
  final rePacks = TextEditingController();

  // عينات
  final smpCartons = TextEditingController();
  final smpPacks = TextEditingController();
  final smpReason = TextEditingController();
  
  String? _selectedSampleReason;
  final List<String> _reasonOptions = ['ترويج منتج جديد', 'عينة مجانية للزبائن', 'تعويض ودي للمحل', 'أخرى'];
  bool showExtras = false;

  @override
  void dispose() {
    sCartons.dispose();
    sPacks.dispose();
    rfCartons.dispose();
    rfPacks.dispose();
    reCartons.dispose();
    rePacks.dispose();
    smpCartons.dispose();
    smpPacks.dispose();
    smpReason.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    _syncFromProp();
  }

  @override
  void didUpdateWidget(covariant _AccordionProductCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.product.id != oldWidget.product.id) {
      _syncFromProp();
    }
  }

  void _syncFromProp() {
    if (widget.cartItem != null) {
      final item = widget.cartItem!;
      sCartons.text = item.cartons > 0 ? item.cartons.toString() : '';
      sPacks.text = item.packs > 0 ? item.packs.toString() : '';
      rfCartons.text = item.returnFactoryCartons > 0 ? item.returnFactoryCartons.toString() : '';
      rfPacks.text = item.returnFactoryPacks > 0 ? item.returnFactoryPacks.toString() : '';
      reCartons.text = item.returnExpiredCartons > 0 ? item.returnExpiredCartons.toString() : '';
      rePacks.text = item.returnExpiredPacks > 0 ? item.returnExpiredPacks.toString() : '';
      smpCartons.text = item.sampleCartons > 0 ? item.sampleCartons.toString() : '';
      smpPacks.text = item.samplePacks > 0 ? item.samplePacks.toString() : '';
      
      if (item.sampleReason.isNotEmpty) {
        if (_reasonOptions.contains(item.sampleReason)) {
          _selectedSampleReason = item.sampleReason;
        } else {
          _selectedSampleReason = 'أخرى';
          smpReason.text = item.sampleReason;
        }
      } else {
        _selectedSampleReason = null;
      }
    } else {
      sCartons.clear(); sPacks.clear();
      rfCartons.clear(); rfPacks.clear();
      reCartons.clear(); rePacks.clear();
      smpCartons.clear(); smpPacks.clear(); smpReason.clear();
      _selectedSampleReason = null;
    }
  }

  void _commitToBloc() {
    int sc = int.tryParse(sCartons.text) ?? 0;
    int sp = int.tryParse(sPacks.text) ?? 0;
    int rfc = int.tryParse(rfCartons.text) ?? 0;
    int rfp = int.tryParse(rfPacks.text) ?? 0;
    int rec = int.tryParse(reCartons.text) ?? 0;
    int rep = int.tryParse(rePacks.text) ?? 0;
    int smpC = int.tryParse(smpCartons.text) ?? 0;
    int smpP = int.tryParse(smpPacks.text) ?? 0;

    // +++ الكي الجراحي لـ Bug 3: لا نحذف المنتج فوراً أثناء تصفير الحقل كي لا يضيع تركيز الكيبورد +++
    // سيتم إرساله للـ BLoC بكميات صفرية، وسيتولى البلوك فلترته عند الحفظ النهائي.
    final updatedItem = CartItemModel(
      productVariantId: widget.product.id,
      name: widget.product.name,
      pricePerCarton: widget.product.pricePerCarton,
      pricePerPack: widget.product.pricePerPack,
      packsPerCarton: widget.product.packsPerCarton,
      availableCartons: widget.product.currentCartons,
      availablePacks: widget.product.currentPacks,
      cartons: sc,
      packs: sp,
      returnFactoryCartons: rfc,
      returnFactoryPacks: rfp,
      returnExpiredCartons: rec,
      returnExpiredPacks: rep,
      sampleCartons: smpC,
      samplePacks: smpP,
      sampleReason: _selectedSampleReason == 'أخرى' ? smpReason.text : (_selectedSampleReason ?? ''),
    );

    widget.visitBloc.add(AddOrUpdateCartItem(updatedItem));
    widget.onCartUpdated();
  }

  Widget _buildStepper(String label, TextEditingController controller, {Color iconColor = Colors.blue}) {
    return SizedBox(
      height: 60,
      child: TextField(
        controller: controller,
        onChanged: (_) => _commitToBloc(), 
        textAlign: TextAlign.center,
        keyboardType: TextInputType.number,
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 20),
        decoration: InputDecoration(
          labelText: label,
          labelStyle: TextStyle(color: iconColor, fontWeight: FontWeight.bold, fontSize: 13),
          floatingLabelBehavior: FloatingLabelBehavior.always,
          contentPadding: const EdgeInsets.symmetric(vertical: 10),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade300)),
          prefixIcon: IconButton(
            icon: const Icon(Icons.remove_circle_outline, color: Colors.red),
            onPressed: () {
              HapticFeedback.lightImpact();
              int curr = int.tryParse(controller.text) ?? 0;
              if (curr > 0) {
                // +++ الكي الجراحي لـ Bug 9: إبقاء مؤشر الكيبورد في نهاية النص لمنع طفرات الكتابة +++
                final newVal = (curr - 1).toString();
                controller.value = TextEditingValue(text: newVal, selection: TextSelection.collapsed(offset: newVal.length));
                _commitToBloc(); 
              }
            }
          ),
          suffixIcon: IconButton(
            icon: Icon(Icons.add_circle_outline, color: iconColor),
            onPressed: () {
              HapticFeedback.lightImpact();
              int curr = int.tryParse(controller.text) ?? 0;
              final newVal = (curr + 1).toString();
              controller.value = TextEditingValue(text: newVal, selection: TextSelection.collapsed(offset: newVal.length));
              _commitToBloc(); 
            }
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    bool isInCart = widget.cartItem != null;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 400),
      curve: Curves.fastOutSlowIn,
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: showExtras ? Colors.yellow.shade50.withValues(alpha: 0.3) : Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: isInCart ? Colors.green.shade400 : Colors.blue.shade100, width: isInCart ? 2.0 : 1.5),
      ),
      child: Column(
        children: [
          ListTile(
            onTap: () {
              HapticFeedback.selectionClick();
              setState(() => showExtras = !showExtras);
            },
            leading: Icon(isInCart ? Icons.check_circle : Icons.inventory_2_outlined, color: isInCart ? Colors.blue : Colors.grey),
            title: Text(widget.product.name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
            subtitle: Text('المتوفر: ${widget.product.currentCartons} ك | ${widget.product.currentPacks} ح', style: const TextStyle(fontSize: 12)),
            trailing: Icon(showExtras ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down, color: Colors.blue),
          ),
          Padding(
            padding: const EdgeInsets.all(12.0),
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(child: _buildStepper("كراتين المبيع", sCartons, iconColor: Colors.green)),
                    const SizedBox(width: 10),
                    Expanded(child: _buildStepper("حبات المبيع", sPacks, iconColor: Colors.green)),
                  ],
                ),
                AnimatedCrossFade(
                  firstChild: const SizedBox.shrink(),
                  secondChild: Column(
                    children: [
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(color: Colors.blue.shade50.withValues(alpha: 0.3), borderRadius: BorderRadius.circular(15), border: Border.all(color: Colors.blue.shade100)),
                        child: Column(
                          children: [
                            // +++ واجهة العدادات الذكية الموحدة (بدون كبسات وهمية) +++
                            Row(
                              children: [
                                Expanded(child: _buildStepper("كراتين تالف مصنع (🔁)", rfCartons, iconColor: Colors.orange)),
                                const SizedBox(width: 8),
                                Expanded(child: _buildStepper("حبات تالف مصنع (🔁)", rfPacks, iconColor: Colors.orange)),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Row(
                              children: [
                                Expanded(child: _buildStepper("كراتين إكسباير (🔁)", reCartons, iconColor: Colors.deepOrange)),
                                const SizedBox(width: 8),
                                Expanded(child: _buildStepper("حبات إكسباير (🔁)", rePacks, iconColor: Colors.deepOrange)),
                              ],
                            ),
                            const Divider(height: 24),
                            Row(
                              children: [
                                Expanded(child: _buildStepper("كراتين العينات (🎁)", smpCartons, iconColor: Colors.purple)),
                                const SizedBox(width: 8),
                                Expanded(child: _buildStepper("حبات العينات (🎁)", smpPacks, iconColor: Colors.purple)),
                              ],
                            ),
                            const SizedBox(height: 8),
                            DropdownButtonFormField<String>(
                              value: _selectedSampleReason,
                              decoration: InputDecoration(
                                hintText: 'اختر سبب صرف العينة (إجباري)',
                                filled: true,
                                fillColor: Colors.white,
                                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                              ),
                              items: _reasonOptions.map((String reason) {
                                return DropdownMenuItem<String>(
                                  value: reason,
                                  child: Text(reason, style: const TextStyle(fontSize: 13)),
                                );
                              }).toList(),
                              onChanged: (String? newValue) {
                                setState(() {
                                  _selectedSampleReason = newValue;
                                  // +++ إضافة الأقواس إجبارياً لإرضاء الـ Linter +++
                                  if (newValue != 'أخرى') {
                                    smpReason.text = newValue ?? '';
                                  } else {
                                    smpReason.clear();
                                  }
                                });
                                _commitToBloc();
                              },
                            ),
                            if (_selectedSampleReason == 'أخرى') ...[
                              const SizedBox(height: 8),
                              TextField(
                                controller: smpReason,
                                onChanged: (_) => _commitToBloc(),
                                decoration: InputDecoration(hintText: 'اكتب السبب بالتفصيل...', filled: true, fillColor: Colors.white, border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)), contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10)),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ],
                  ),
                  crossFadeState: showExtras ? CrossFadeState.showSecond : CrossFadeState.showFirst,
                  duration: const Duration(milliseconds: 300),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}