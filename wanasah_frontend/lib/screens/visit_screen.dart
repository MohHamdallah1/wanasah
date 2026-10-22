import 'package:flutter/material.dart';
import 'dart:async';
import 'package:map_launcher/map_launcher.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:convert';
import '../core/db/local_database.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import '../blocs/visit/visit_bloc.dart';
import '../models/cart_item_model.dart';
import '../features/visits/presentation/visit_catalog.dart';
import '../features/visits/presentation/confirm_visit_field_submission.dart';
import '../features/visits/presentation/invoice/visit_invoice_receipt.dart';
import '../features/visits/presentation/visit_field_failure.dart';
import '../features/visits/presentation/visit_field_strings.dart';
import '../features/visits/application/visit_money_input.dart';
import 'dart:developer' as developer;

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
  // +++ الدرع البصري: متغيرات معلومات الاتصال +++
  String? _shopOwner;
  String? _shopPhone;

  // +++ Helper Functions: دوال مساعدة موحدة للتحقق الآمن +++
  
  /// C9, H17, H18: تحليل نقدي آمن مع رفض NaN/Infinity/sالبة
  double parseSafeMoney(String text) {
    if (text.trim().isEmpty) return 0.0;
    // استبدال الفواصل العربية/العادية بنقطة عشرية
    final normalized = text.replaceAll(RegExp(r'[,،]'), '.').trim();
    final value = double.tryParse(normalized);
    // إذا فشل التحليل (مثلاً بسبب وجود نقطتين 12.3.4) نرفض الرقم تماماً
    if (value == null || !value.isFinite || value < 0) return double.nan;
    return value;
  }

  @override
  void initState() {
    super.initState();
    _visitBloc = VisitBloc();

    // +++  للـ Jank (التداخل): تأخير العمليات الثقيلة حتى ينتهي Navigator Animation +++
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _visitBloc.add(LoadVisitCatalog(widget.shopBalance));
        _fetchDataOnInit();
      }
    });

    _cashController.addListener(() {
      // +++ C9, H17, H18: Safe Money Parsing +++
      final amount = parseSafeMoney(_cashController.text);
      if (!amount.isNaN) {
        _visitBloc.add(UpdateCashCollected(amount));
      }
    });

    // +++ ربط حقل تسديد الدين بالعقل المدبر لتحديث الذمة لحظياً +++
    _debtPaidController.addListener(() {
      // +++ C9, H17, H18: Safe Money Parsing +++
      final amount = parseSafeMoney(_debtPaidController.text);
      if (!amount.isNaN) {
        _visitBloc.add(UpdateDebtPaid(amount));
      }
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
                try {
                  final payload = jsonDecode(p['payload'] as String);
                  // +++ توحيد المقارنة كنصوص لتفادي الانهيار مع الـ IDs الغريبة +++
                  return payload['visitId']?.toString() == widget.visitId.toString() || 
                         payload['visit_id']?.toString() == widget.visitId.toString();
                } catch (_) {
                  return false; // تجاهل السجل التالف بصمت
                }
              }
              return false;
            });

          if (!mounted) return;

          // +++  السماح بتعديل المسودة الأوفلاين (Local Authority) +++
          if (isOfflineDraft) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  VisitFieldStrings.of(context).t('unresolvedCommand'),
                ),
                backgroundColor: Colors.blue,
                duration: const Duration(seconds: 3),
              ),
            );
          }

          // +++  (متوسط 3): إنذار الكاش المزلزل لمنع السرقة أو نسيان إرجاع المال +++
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
          try {
            final payload = jsonDecode(p['payload'] as String);
            // +++ استخدام toString() لتوحيد المقارنة ومنع كراش الـ Types +++
            if (payload['visitId']?.toString() == widget.visitId.toString() || 
                payload['visit_id']?.toString() == widget.visitId.toString()) {
              offlinePayload = payload;
              break;
            }
          } catch (e) {
            developer.log('[VisitScreen] Ignored corrupted pending sync payload: $e');
            // استمر في الحلقة ولا تدمر الشاشة
          }
        }
      }

      // +++  استخراج الحالة للتحقق من المزامنة العكسية بأمان +++
      final String? currentStatus =
          visitData['status'] ?? visitData['visit_status'];

      if (offlinePayload != null) {
        final cashDouble = double.tryParse(offlinePayload['cash_collected']?.toString() ?? '0') ?? 0.0;
        _cashController.text = canonicalVisitMoney(offlinePayload['cash_collected']?.toString() ?? '');
        final debtDouble = double.tryParse(offlinePayload['debt_paid']?.toString() ?? '0') ?? 0.0;
        _debtPaidController.text =
            canonicalVisitMoney(offlinePayload['debt_paid']?.toString() ?? '');
        _notesController.text =
            offlinePayload['notes'] ?? offlinePayload['no_sale_reason'] ?? '';

        // +++  (حرج 5): استرجاع السلة والتوالف من الخزنة السرية إذا كانت الزيارة أوفلاين +++
        if (offlinePayload['cart_items'] != null ||
            offlinePayload['returns'] != null) {
          
          // +++  الأضخم: إجبار الكود على الانتظار حتى يجهز البلوك (VisitReady) قبل حقن الفاتورة +++
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
      developer.log('[VisitScreen] Initialization Error: $e');
      _error = 'فشل تهيئة الزيارة. يرجى التأكد من استقرار التطبيق وإعادة فتح الصفحة.';
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  // --- دالة الحماية عند محاولة الرجوع ---
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
          listener: (context, state) async {
            // +++ C1: الدرع الواقي - فحص mounted قبل أي استخدام للـ context +++
            if (!context.mounted) return;

            if (state is VisitFieldSubmissionFailure) {
              setState(() => _isSubmitting = false);
              await showVisitFieldFailure(context, failure: state.failure, issue: state.issue);
            } else if (state is VisitError) {
              setState(() => _isSubmitting = false);
              ScaffoldMessenger.of(context).clearSnackBars(); // +++   مسح الطابور +++
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(state.message), backgroundColor: Colors.red),
              );
            } else if (state is VisitSubmissionSuccess) {
              setState(() => _isSubmitting = false);
              _hasChanges = false;
              await showDialog<void>(
                context: context, barrierDismissible: false,
                builder: (_) => VisitInvoiceReceipt(
                  visitId: state.visitId, disposition: state.disposition,
                  initial: state.invoice, read: _visitBloc.committedInvoice),
              );
              if (context.mounted && ModalRoute.of(context)?.isCurrent == true) {
                Navigator.pop(context, true);
              }
            } else if (state is VisitReady) {
              // +++ كي جراحي: تغذية القناة الميتة (notes) وإرواءها بالماء كما أراد البوت (عند الاستعادة فقط) +++
              if (state.notes != null && state.notes != _notesController.text) {
                _notesController.text = state.notes!;
              }
            }
          },
        child: PopScope(
          canPop: false,
          onPopInvokedWithResult: (bool didPop, Object? result) async {
            if (didPop) return;
            // +++ الدرع الفولاذي: منع المندوب من الهرب أو الخروج أثناء عملية التشفير والحفظ +++
            if (_isSubmitting) return; 
            
            if (_isCatalogMode) {
              setState(() => _isCatalogMode = false);
              return;
            }
            final bool shouldPop = await _onWillPop();
            // +++   استخدام context.mounted بشكل صريح وحصري بعد الـ await لمنع خطأ الـ Async Gap +++
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
                    // +++  لـ Bug 2: تفويض الخروج للـ PopScope لمنع تكرار رسالة التأكيد مرتين +++
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
    final bool isLocked = _isSubmitting || _isOnBreak || !_isAuthorizedToSell; // +++ تحديد حالة القفل العام +++

    return BlocBuilder<VisitBloc, VisitState>(
      // +++ الدرع البصري (Anti-Flicker): تجاهل حالات الخطأ والنجاح في بناء الواجهة لتبقى الفاتورة مرئية ولا ترمش أبداً +++
      buildWhen: (previous, current) => current is! VisitError && current is! VisitSubmissionSuccess,
      builder: (context, state) {
        if (state is VisitLoading) return const Center(child: CircularProgressIndicator());
        
        if (state is VisitReady) {
          if (_isCatalogMode) {
            return Column(
              children: [
                VisitCatalog(
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
            // +++  لـ Bug 7: عرض توالف وإكسباير مصنع بدلاً من مصفوفة الـ returns الفارغة +++
            subtitle: Text(VisitFieldStrings.of(context).quantitySummary(item.cartons, item.packs,
              item.returnFactoryCartons + item.returnExpiredCartons + item.returnDamagedCartons,
              item.returnFactoryPacks + item.returnExpiredPacks + item.returnDamagedPacks)),
            trailing: Text(
              '${VisitFieldStrings.of(context).t('estimate')}: ${item.totalSalePrice.toStringAsFixed(3)}', 
              style: TextStyle(color: isLocked ? Colors.grey : (item.totalSalePrice > 0 ? Colors.green : Colors.orange), fontWeight: FontWeight.bold)
            ),
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
                            // +++  لخطأ الـ Async Gap: فحص الـ context حصرياً +++
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
              Text(
                VisitFieldStrings.of(context).t('estimate'),
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              Text(
                state.netInvoice.toStringAsFixed(3),
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
                    labelText: VisitFieldStrings.of(context).t('cash'),
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
                    labelText: VisitFieldStrings.of(context).t('debt'),
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
              labelText: VisitFieldStrings.of(context).t('notes'),
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
                VisitFieldStrings.of(context).t(widget.visitStatus == 'Completed' ? 'correct' : 'finish'),
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
      // +++ الدرع المعماري: حماية كراش الخرائط ותجاهل 0.0 +++
      if (lat != null && lng != null && lat != 0.0 && lng != 0.0) {
        final bool isGoogleMapsAvailable = await MapLauncher.isMapAvailable(MapType.google) ?? false;
        if (isGoogleMapsAvailable) {
          await MapLauncher.showMarker(
            mapType: MapType.google,
            coords: Coords(lat, lng),
            title: title,
            description: description ?? '',
          );
        } else {
          final availableMaps = await MapLauncher.installedMaps;
          if (availableMaps.isNotEmpty) {
            await availableMaps.first.showMarker(coords: Coords(lat, lng), title: title);
          } else {
            if (!mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('لا يوجد تطبيق خرائط مثبت')));
          }
        }
      } else if (link != null && link.trim().isNotEmpty) {
        String cleanLink = link.trim();
        if (!cleanLink.startsWith('http://') && !cleanLink.startsWith('https://')) {
          cleanLink = 'https://$cleanLink';
        }
        final Uri url = Uri.parse(cleanLink);
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
    if (_isSubmitting || _isOnBreak || !_isAuthorizedToSell) return;
    setState(() => _isSubmitting = true);
    var dispatched = false;
    try {
      if (await _visitBloc.hasUnresolvedVisit(widget.visitId)) {
        if (mounted) await showVisitFieldFailure(context, issue: 'unresolvedCommand');
        return;
      }
      if (!mounted) return;
      // Preserve the existing cached route/stock UX gates. Neither determines
      // tax readiness, pricing, FEFO or final Backend acceptance.
      if (state.cart.any((item) => !item.hasEnoughInventory)) {
        await showVisitFieldFailure(context, issue: 'quantityUnavailable');
        return;
      }
      if (!_isEmergency && _shopZone != null && _allowedZone != null &&
          _shopZone != _allowedZone) {
        await showVisitFieldFailure(context, issue: 'outsideRoute');
        return;
      }
      final confirmation = await confirmVisitFieldSubmission(context,
        visitId: widget.visitId, cart: state.cart,
        notes: _notesController.text.trim(),
        cashText: _cashController.text, debtText: _debtPaidController.text,
        readiness: _visitBloc.commercialReadiness,
        returns: _visitBloc.returnResolution, preview: _visitBloc.invoicePreview);
      if (confirmation == null || !mounted) return;
      dispatched = true;
      safeAddVisitEvent(SubmitVisit(
        visitId: widget.visitId, outcome: confirmation.outcome,
        notes: confirmation.notes, debtPaid: state.debtPaid,
        exactCashCollected: confirmation.cash, exactDebtPaid: confirmation.debt,
        resolvedReturns: confirmation.returns, saleConfirmation: confirmation.sale,
      ));
    } catch (_) {
      if (mounted) await showVisitFieldFailure(context);
    } finally {
      if (mounted && !dispatched) setState(() => _isSubmitting = false);
    }
  }

  // +++ C3: Safe Bloc Event Addition with mounted check +++
  void safeAddVisitEvent(VisitEvent event) {
    if (!mounted) return;
    _visitBloc.add(event);
  }
} // نهاية كلاس _VisitScreenState
