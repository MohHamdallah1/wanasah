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
  double _maxDebtLimit = 0.0;

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
      _hasChanges = true;
      final amount = double.tryParse(_cashController.text) ?? 0.0;
      _visitBloc.add(UpdateCashCollected(amount));
    });

    // +++ ربط حقل تسديد الدين بالعقل المدبر لتحديث الذمة لحظياً +++
    _debtPaidController.addListener(() {
      _hasChanges = true;
      final amount = double.tryParse(_debtPaidController.text) ?? 0.0;
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
        _maxDebtLimit =
            (visitData['max_debt_limit'] as num?)?.toDouble() ?? 0.0;

        _shopLatitude =
            (visitData['latitude'] ?? visitData['shop_latitude'] as num?)
                ?.toDouble();
        _shopLongitude =
            (visitData['longitude'] ?? visitData['shop_longitude'] as num?)
                ?.toDouble();
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
          final double oldCash =
              (visitData['cash_collected'] as num?)?.toDouble() ?? 0.0;
          final double oldDebt =
              (visitData['debt_paid'] as num?)?.toDouble() ?? 0.0;
          final double totalOldMoney = oldCash + oldDebt;

          if (totalOldMoney > 0) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  '🚨 تحذير مالي خطير: هذه الزيارة محصلة مسبقاً بمبلغ (${totalOldMoney.toStringAsFixed(2)} د.أ). إذا قمت بالحفظ، سيقوم النظام بتصفير هذا المبلغ، ويجب عليك إعادته يدوياً لصاحب المحل فوراً!',
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
        final cashDouble =
            (offlinePayload['cash_collected'] as num?)?.toDouble() ?? 0.0;
        _cashController.text =
            (cashDouble == 0.0) ? '' : cashDouble.toStringAsFixed(2);
        final debtDouble =
            (offlinePayload['debt_paid'] as num?)?.toDouble() ?? 0.0;
        _debtPaidController.text =
            (debtDouble == 0.0) ? '' : debtDouble.toStringAsFixed(2);
        _notesController.text =
            offlinePayload['notes'] ?? offlinePayload['no_sale_reason'] ?? '';

        // +++ النسف المعماري (حرج 5): استرجاع السلة والتوالف من الخزنة السرية إذا كانت الزيارة أوفلاين +++
        if (offlinePayload['cart_items'] != null ||
            offlinePayload['returns'] != null) {
          
          // +++ الكي الجراحي الأضخم: إجبار الكود على الانتظار حتى يجهز البلوك (VisitReady) قبل حقن الفاتورة +++
          if (_visitBloc.state is! VisitReady) {
            await _visitBloc.stream.firstWhere((state) => state is VisitReady);
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
          _cashController.text = cashDouble > 0 ? cashDouble.toStringAsFixed(2) : '';
          _debtPaidController.text = debtDouble > 0 ? debtDouble.toStringAsFixed(2) : '';
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
        final double oldCash = (visitData['cash_collected'] as num?)?.toDouble() ?? 0.0;
        final double oldDebt = (visitData['debt_paid'] as num?)?.toDouble() ?? 0.0;

        if (cartJson != null || returnsJson != null) {
          
          // +++ حماية التزامن: الانتظار حتى يجهز البلوك لاستقبال الفاتورة القديمة +++
          if (_visitBloc.state is! VisitReady) {
            await _visitBloc.stream.firstWhere((state) => state is VisitReady);
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
            _cashController.text = oldCash > 0 ? oldCash.toStringAsFixed(2) : '';
            _debtPaidController.text = oldDebt > 0 ? oldDebt.toStringAsFixed(2) : '';
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
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(state.message),
                backgroundColor: Colors.red,
              ),
            );
          } else if (state is VisitSubmissionSuccess) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('تم حفظ العملية بنجاح.'),
                backgroundColor: Colors.green,
              ),
            );
            Navigator.pop(context, true);
          }
        },
        child: PopScope(
          canPop: false,
          onPopInvokedWithResult: (bool didPop, Object? result) async {
            if (didPop) {
              return;
            }
            final bool shouldPop = await _onWillPop();
            if (shouldPop && context.mounted) {
              Navigator.of(context).pop();
            }
          },
          child: Scaffold(
            // +++ النسف المعماري لظاهرة الأشباح: إعطاء لون صلب يمنع شفافية الشاشات أثناء التنقل +++
            backgroundColor: Colors.transparent,
            appBar: AppBar(
              backgroundColor: Colors.transparent,
              elevation: 0,
              surfaceTintColor:
                  Colors
                      .transparent, // لمنع تغيير لون الـ AppBar عند التمرير تحته
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
    return IgnorePointer(
      ignoring: _isOnBreak,
      child: BlocBuilder<VisitBloc, VisitState>(
        builder: (context, state) {
          if (state is VisitLoading) return const Center(child: CircularProgressIndicator());
          if (state is VisitReady) {
            // الحالة 1: وضع اختيار المنتجات (الكاتالوج المطور 2026)
            if (_isCatalogMode) {
              return Column(
                children: [
                  // سطر البحث والإغلاق المدمج (بدون AppBar)
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

            // الحالة 2: وضع الفاتورة الرئيسي (السلة)
            return Column(
              children: [
                _buildSafetyBanners(), // استراحات وصلاحيات
                Expanded(
                  child: state.cart.isEmpty 
                    ? _buildEmptyCartPlaceholder() 
                    : _buildInvoiceListView(state.cart),
                ),
                _buildFixedFooter(state),
              ],
            );
          }
          return const SizedBox.shrink();
        },
      ),
    );
  }

  // دالة مساعدة لبناء شكل الفاتورة النظيف
  Widget _buildInvoiceListView(List<CartItemModel> cart) {
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: cart.length + 1,
      itemBuilder: (context, index) {
        if (index == cart.length) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 20),
            child: ElevatedButton.icon(
              onPressed: () => setState(() => _isCatalogMode = true),
              icon: const Icon(Icons.add_shopping_cart),
              label: const Text('إضافة أصناف أخرى', style: TextStyle(fontWeight: FontWeight.bold)),
              style: ElevatedButton.styleFrom(backgroundColor: Colors.blue.shade50, foregroundColor: Colors.blue.shade800, padding: const EdgeInsets.all(15)),
            ),
          );
        }
        final item = cart[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 10),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15), side: BorderSide(color: Colors.grey.shade200)),
          child: ListTile(
            title: Text(item.name, style: const TextStyle(fontWeight: FontWeight.bold)),
            subtitle: Text('المبيع: ${item.cartons}ك | ${item.packs}ح  -  توالف: ${item.returns.length}'),
            trailing: Text('${item.totalSalePrice.toStringAsFixed(2)} د.أ', style: const TextStyle(color: Colors.green, fontWeight: FontWeight.bold)),
            onTap: () => setState(() => _isCatalogMode = true), // العودة للكاتالوج للتعديل
          ),
        );
      },
    );
  }

  Widget _buildEmptyCartPlaceholder() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.shopping_basket_outlined, size: 100, color: Colors.grey.shade300),
          const SizedBox(height: 20),
          const Text('الفاتورة فارغة حالياً', style: TextStyle(fontSize: 18, color: Colors.grey, fontWeight: FontWeight.bold)),
          const SizedBox(height: 30),
          ElevatedButton.icon(
            onPressed: (_isAuthorizedToSell && !_isOnBreak) 
                ? () => setState(() => _isCatalogMode = true) 
                : null, // الزر سيتعطل تلقائياً إذا لم يبدأ العمل
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

  // --- الفوتر الثابت الموحد ---
  Widget _buildFixedFooter(VisitReady state) {
    return Container(
      padding: const EdgeInsets.all(16),
      // +++ حل تحذير Deprecated: استبدال withOpacity بـ withValues +++
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.1),
            blurRadius: 10,
            spreadRadius: 1,
          ),
        ],
      ),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'إجمالي الفاتورة الصافي:',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              Text(
                '${state.netInvoice.toStringAsFixed(2)} د.أ',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Colors.blue,
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
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'الكاش المستلم',
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.money),
                    isDense: true,
                  ),
                  onChanged: (_) => _hasChanges = true,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextField(
                  controller: _debtPaidController,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'تحصيل ذمة سابقة',
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.account_balance_wallet),
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
            decoration: const InputDecoration(
              labelText: 'ملاحظات',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.note),
              isDense: true,
            ),
            onChanged: (_) => _hasChanges = true,
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            height: 45,
            child: ElevatedButton(
              onPressed:
                  _isSubmitting
                      ? null
                      : () =>
                          _validateAndSubmitSmart(state), // +++ قفل الزر +++
              style: ElevatedButton.styleFrom(
                backgroundColor:
                    widget.visitStatus == 'Completed'
                        ? Colors.orange[700]
                        : Colors.teal,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              child: Text(
                widget.visitStatus == 'Completed'
                    ? 'تعديل الفاتورة واعتمادها'
                    : 'إنهاء الزيارة',
                style: const TextStyle(
                  fontSize: 18,
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
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
    // 1. حماية الاستراحة والصلاحية
    if (_isOnBreak || !_isAuthorizedToSell) return;

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

    // 3. التحقق من الدفع والذمم
    // +++ الكي الجراحي الميداني (Regex): التقاط الفاصلة العربية والإنجليزية معاً وتحويلها لنقطة +++
    final double cashEntered =
        double.tryParse(
          _cashController.text.replaceAll(RegExp(r'[,،]'), '.').trim(),
        ) ??
        0.0;

    final double debtPaidEntered =
        double.tryParse(
          _debtPaidController.text.replaceAll(RegExp(r'[,،]'), '.').trim(),
        ) ??
        0.0;

    if (debtPaidEntered > widget.shopBalance && widget.shopBalance > 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('مبلغ السداد أكبر من ذمة المحل!'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    if (cashEntered > state.netInvoice) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('الكاش المستلم أكبر من قيمة الفاتورة الصافية!'),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    // 4. حماية سقف الدين
    if (state.expectedNewBalance > _maxDebtLimit) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'مرفوض: الدين الجديد (${state.expectedNewBalance.toStringAsFixed(2)}) يتجاوز سقف المحل (${_maxDebtLimit.toStringAsFixed(2)}).',
          ),
          backgroundColor: Colors.red,
          duration: const Duration(seconds: 4),
        ),
      );
      return;
    }

    // 5. استنتاج النتيجة الذكي (Smart Outcome)
    String finalOutcome = 'NoSale';
    bool hasSales = state.cart.any((i) => i.cartons > 0 || i.packs > 0);
    bool hasReturns = state.cart.any((i) => i.returns.isNotEmpty);
    bool hasSamples = state.cart.any(
      (i) => i.sampleCartons > 0 || i.samplePacks > 0,
    );

    if (hasSales) {
      finalOutcome = 'Sale';
    } else if (hasReturns || hasSamples) {
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

    // +++ النسف المعماري (Pre-emptive Strike): مسح الفاتورة الأوفلاين القديمة إن وُجدت قبل إرسال الجديدة +++
    if (widget.visitStatus == 'Completed') {
      try {
        await LocalDatabase.instance.revertOfflineVisit(widget.visitId);
      } catch (e) {
        developer.log('Error reverting offline visit: $e');
      }
    }

    // 6. توجيه الضربة النهائية (إرسال الأمر للمحاسب)
    _visitBloc.add(
      SubmitVisit(
        visitId: widget.visitId,
        outcome: finalOutcome,
        debtPaid: debtPaidEntered, // تم إرسال الدفعة بشكل صحيح
        notes: _notesController.text.trim(),
      ),
    );
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
  final Map<int, Map<String, dynamic>> _drafts = {};

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
                  product: product,
                  cartItem: cartItem,
                  isExpanded: true, 
                  draftsMap: _drafts,
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
  final Map<int, Map<String, dynamic>> draftsMap; // +++ استقبال المسودات +++
  final VoidCallback onToggle;
  final VisitBloc visitBloc;
  final VoidCallback onCartUpdated;

  const _AccordionProductCard({
    required this.product,
    required this.cartItem,
    required this.isExpanded,
    required this.draftsMap,
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
  bool showExtras = false;

  // توالف
  List<Map<String, dynamic>> localReturns = [];
  final newRCartons = TextEditingController();
  final newRPacks = TextEditingController();
  String? newReturnType;

  // عينات
  final smpCartons = TextEditingController();
  final smpPacks = TextEditingController();
  final smpReason = TextEditingController();

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
      localReturns = List.from(item.returns);
      smpCartons.text = item.sampleCartons > 0 ? item.sampleCartons.toString() : '';
      smpPacks.text = item.samplePacks > 0 ? item.samplePacks.toString() : '';
      smpReason.text = item.sampleReason;
    } else {
      sCartons.clear();
      sPacks.clear();
      localReturns.clear();
      smpCartons.clear();
      smpPacks.clear();
      smpReason.clear();
      newRCartons.clear();
      newRPacks.clear();
      newReturnType = null;
    }
  }

  // +++ محرك الحفظ الفوري (السرعة الخارقة لمنع ضياع أي رقم) +++
  void _commitToBloc() {
    int sc = int.tryParse(sCartons.text) ?? 0;
    int sp = int.tryParse(sPacks.text) ?? 0;
    int smpC = int.tryParse(smpCartons.text) ?? 0;
    int smpP = int.tryParse(smpPacks.text) ?? 0;

    bool hasData = sc > 0 || sp > 0 || localReturns.isNotEmpty || smpC > 0 || smpP > 0;

    if (!hasData) {
      if (widget.cartItem != null) {
        widget.visitBloc.add(RemoveCartItem(widget.product.id));
        widget.onCartUpdated();
      }
      return;
    }

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
      returns: localReturns,
      sampleCartons: smpC,
      samplePacks: smpP,
      sampleReason: smpReason.text,
    );

    widget.visitBloc.add(AddOrUpdateCartItem(updatedItem));
    widget.onCartUpdated();
  }

  void _addReturnLogic() {
    if (newReturnType == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('اختر نوع التلف أولاً!'), backgroundColor: Colors.red));
      return;
    }
    int c = int.tryParse(newRCartons.text) ?? 0;
    int p = int.tryParse(newRPacks.text) ?? 0;
    if (c > 0 || p > 0) {
      setState(() {
        final existingIdx = localReturns.indexWhere((r) => r['type'] == newReturnType);
        if (existingIdx != -1) {
          localReturns[existingIdx]['cartons'] += c;
          localReturns[existingIdx]['packs'] += p;
        } else {
          localReturns.add({'cartons': c, 'packs': p, 'type': newReturnType});
        }
        newRCartons.clear();
        newRPacks.clear();
        newReturnType = null;
      });
      _commitToBloc(); // حفظ فوري بعد إضافة التلف
    }
  }

  // +++ تصميم أزرار التوالف الجديد 2026 +++
  Widget _buildReturnTypeSmallBtn(String type, String label) {
    bool isSelected = newReturnType == type;
    // +++ تصميم نيون مستقبليInspired: استخدام لون النيون (0xFF00F2FE) للأزرار بدلاً من الرمادي +++
    Color baseColor = const Color(0xFF00F2FE); 
    return Expanded(
      child: InkWell(
        onTap: () => setState(() => newReturnType = type),
        borderRadius: BorderRadius.circular(20), // زيادة الانحناء
        child: Container(
          height: 40,
          decoration: BoxDecoration(
            color: isSelected ? baseColor : Colors.white,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: isSelected ? baseColor : Colors.grey.shade300, width: 1.5)
          ),
          child: Center(
            child: Text(
              label, 
              style: TextStyle(
                fontSize: 12, 
                fontWeight: FontWeight.bold, 
                color: isSelected ? Colors.white : Colors.grey.shade700
              )
            )
          ),
        ),
      ),
    );
  }

  Widget _buildStepper(String label, TextEditingController controller) {
    return SizedBox(
      height: 60,
      child: TextField(
        controller: controller,
        onChanged: (_) => _commitToBloc(), // +++ حفظ فوري عند الكتابة بالكيبورد +++
        textAlign: TextAlign.center,
        keyboardType: TextInputType.number,
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 20),
        decoration: InputDecoration(
          labelText: label,
          labelStyle: const TextStyle(color: Colors.blue, fontWeight: FontWeight.bold, fontSize: 13),
          floatingLabelBehavior: FloatingLabelBehavior.always,
          contentPadding: const EdgeInsets.symmetric(vertical: 10),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade300)),
          prefixIcon: IconButton(
            icon: const Icon(Icons.remove_circle_outline, color: Colors.red),
            onPressed: () {
              HapticFeedback.lightImpact();
              int curr = int.tryParse(controller.text) ?? 0;
              if (curr > 0) {
                controller.text = (curr - 1).toString();
                _commitToBloc(); // +++ حفظ فوري عند الضغط على الناقص +++
              }
            }
          ),
          suffixIcon: IconButton(
            icon: const Icon(Icons.add_circle_outline, color: Colors.green),
            onPressed: () {
              HapticFeedback.lightImpact();
              int curr = int.tryParse(controller.text) ?? 0;
              controller.text = (curr + 1).toString();
              _commitToBloc(); // +++ حفظ فوري عند الضغط على الزائد +++
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
        // +++ لون مميز (أخضر) إذا كان الصنف مضافاً للسلة، وأزرق باهت إذا كان فارغاً +++
        border: Border.all(color: isInCart ? Colors.green.shade400 : Colors.blue.shade100, width: isInCart ? 2.0 : 1.5),
      ),
      child: Column(
        children: [
          // الرأس: التوسيع فقط عبر السهم
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
          
          // تم حذف الـ Divider هنا لتنظيف التصميم بناءً على طلبك
          
          Padding(
            padding: const EdgeInsets.all(12.0),
            child: Column(
              children: [
                // مبيعات: ظاهرة دائماً ولا تختفي
                Row(
                  children: [
                    Expanded(child: _buildStepper("كراتين المبيع", sCartons)),
                    const SizedBox(width: 10),
                    Expanded(child: _buildStepper("حبات المبيع", sPacks)),
                  ],
                ),

                // قسم التوالف والعينات: مخفي ويظهر فقط عند ضغط السهم
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
                            if (localReturns.isNotEmpty)
                              ...localReturns.asMap().entries.map((e) => Card(elevation: 0, margin: const EdgeInsets.only(bottom: 5), child: ListTile(dense: true, title: Text('${e.value['type'] == 'Expired' ? 'إكسباير' : 'تالف مصنع'} - ${e.value['cartons']} ك | ${e.value['packs']} ح', style: const TextStyle(fontWeight: FontWeight.bold)), trailing: IconButton(icon: const Icon(Icons.delete, color: Colors.red, size: 18), onPressed: () { setState(() => localReturns.removeAt(e.key)); _commitToBloc(); })))),
                            Row(
                              children: [
                                Expanded(child: _buildStepper("كراتين التوالف", newRCartons)),
                                const SizedBox(width: 8),
                                Expanded(child: _buildStepper("حبات التوالف", newRPacks)),
                              ],
                            ),
                            const SizedBox(height: 10),
                            Row(
                              children: [
                                _buildReturnTypeSmallBtn('Factory_Defect', 'تالف مصنع'),
                                const SizedBox(width: 5),
                                _buildReturnTypeSmallBtn('Expired', 'إكسباير'),
                                const SizedBox(width: 10),
                                IconButton.filled(
                                  onPressed: _addReturnLogic, 
                                  icon: const Icon(Icons.check),
                                  style: IconButton.styleFrom(
                                    backgroundColor: Colors.blueGrey.shade600,
                                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20))
                                  ),
                                ),
                              ],
                            ),
                            const Divider(height: 24),
                            Row(
                              children: [
                                Expanded(child: _buildStepper("كراتين العينات", smpCartons)),
                                const SizedBox(width: 8),
                                Expanded(child: _buildStepper("حبات العينات", smpPacks)),
                              ],
                            ),
                            const SizedBox(height: 8),
                            TextField(
                              controller: smpReason,
                              onChanged: (_) => _commitToBloc(),
                              decoration: InputDecoration(hintText: 'سبب صرف العينة (إجباري)', filled: true, fillColor: Colors.white, border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)), contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10)),
                            ),
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