import 'package:flutter/material.dart';
import 'dart:ui';
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
    _visitBloc = VisitBloc()..add(LoadVisitCatalog(widget.shopBalance));

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

    _fetchDataOnInit();
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

          // المنع القطعي: مسودة الأوفلاين
          if (isOfflineDraft) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'مرفوض: الزيارة معلقة بوضع الأوفلاين. يجب مزامنتها مع الإدارة أولاً قبل السماح بتعديلها.',
                ),
                backgroundColor: Colors.red,
                duration: Duration(seconds: 5), // مدة طويلة ليقرأها بوضوح
              ),
            );
            Navigator.pop(context);
            return;
          }

          // التحذير الصارم: فاتورة أونلاين فعلية
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'تنبيه: هذه الزيارة معتمدة مالياً مسبقاً. أي حفظ سيقوم بإلغاء الفاتورة القديمة واعتماد الجديدة كلياً.',
              ),
              backgroundColor: Colors.orange,
              duration: Duration(seconds: 4),
            ),
          );
        }
      }

      // 3. محاولة استرجاع المسودة المالية (Draft) من الخزنة
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

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('تم استرجاع الكاش والملاحظات من المسودة.'),
              backgroundColor: Colors.blue,
            ),
          );
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
    return BlocProvider.value(
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
            backgroundColor:
                Colors
                    .transparent, // +++ جعل الخلفية شفافة لرؤية التدرج العالمي +++
            appBar: AppBar(
              backgroundColor: Colors.transparent,
              elevation: 0,
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
              bottom: PreferredSize(
                preferredSize: const Size.fromHeight(30),
                child: BlocBuilder<VisitBloc, VisitState>(
                  builder: (context, state) {
                    if (state is VisitReady) {
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 8.0),
                        child: Text(
                          'الذمة السابقة: ${widget.shopBalance.toStringAsFixed(2)} | الحالية المتوقعة: ${state.expectedNewBalance.toStringAsFixed(2)}',
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      );
                    }
                    return const SizedBox.shrink();
                  },
                ),
              ),
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
    );
  }

  // --- واجهة السلة الذكية ---
  Widget _buildSmartCartUI() {
    return IgnorePointer(
      ignoring: _isOnBreak,
      child: Column(
        children: [
          if (_isOnBreak)
            Container(
              margin: const EdgeInsets.all(10),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.red[50],
                border: Border.all(color: Colors.red),
              ),
              child: Text(
                'أنت في وقت الاستراحة. العمليات مقفلة.',
                style: TextStyle(
                  color: Colors.red[800],
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          if (!_isAuthorizedToSell)
            Container(
              margin: const EdgeInsets.all(10),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.orange[50],
                border: Border.all(color: Colors.orange),
              ),
              child: Text(
                'غير مصرح لك بالبيع. بانتظار التفعيل.',
                style: TextStyle(
                  color: Colors.orange[800],
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),

          Expanded(
            child: BlocBuilder<VisitBloc, VisitState>(
              builder: (context, state) {
                if (state is VisitLoading) {
                  return const Center(child: CircularProgressIndicator());
                }
                // +++ سد ثغرة التحميل اللانهائي: عرض زر التحديث إذا فشل جلب المنتجات +++
                if (state is VisitError && _isLoading == false) {
                  return Center(
                    child: ElevatedButton.icon(
                      onPressed:
                          () => _visitBloc.add(
                            LoadVisitCatalog(widget.shopBalance),
                          ),
                      icon: const Icon(Icons.refresh),
                      label: const Text('إعادة تحميل المنتجات'),
                    ),
                  );
                }
                if (state is VisitReady) {
                  if (state.cart.isEmpty) {
                    return Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(
                            Icons.shopping_basket_outlined,
                            size: 80,
                            color: Colors.grey,
                          ),
                          const SizedBox(height: 16),
                          const Text(
                            'السلة فارغة، ابدأ بإضافة المنتجات',
                            style: TextStyle(color: Colors.grey, fontSize: 16),
                          ),
                          const SizedBox(height: 24),
                          ElevatedButton.icon(
                            onPressed:
                                _isAuthorizedToSell
                                    ? () => _showProductSearch(state.catalog)
                                    : null,
                            icon: const Icon(Icons.add),
                            label: const Text(
                              'إضافة منتج للزيارة',
                              style: TextStyle(fontSize: 18),
                            ),
                            style: ElevatedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 32,
                                vertical: 12,
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  } else {
                    return ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: state.cart.length + 1,
                      itemBuilder: (context, index) {
                        if (index == state.cart.length) {
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            child: ElevatedButton.icon(
                              onPressed:
                                  _isAuthorizedToSell
                                      ? () => _showProductSearch(state.catalog)
                                      : null,
                              icon: const Icon(Icons.add_circle_outline),
                              label: const Text('إضافة صنف آخر'),
                            ),
                          );
                        }
                        final item = state.cart[index];
                        return Card(
                          elevation: 2,
                          margin: const EdgeInsets.only(bottom: 10),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: ListTile(
                            title: Text(
                              item.name,
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            subtitle: Text(
                              'مبيع: ${item.cartons} ك، ${item.packs} ح | توالف: ${item.returnCartons} ك',
                            ),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(
                                  '${item.totalSalePrice.toStringAsFixed(2)} د.أ',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.bold,
                                    color: Colors.green,
                                  ),
                                ),
                                IconButton(
                                  icon: const Icon(
                                    Icons.edit,
                                    color: Colors.blue,
                                  ),
                                  onPressed: () => _showMagicDialog(item),
                                ),
                                IconButton(
                                  icon: const Icon(
                                    Icons.delete,
                                    color: Colors.red,
                                  ),
                                  onPressed: () {
                                    _hasChanges = true;
                                    _visitBloc.add(
                                      RemoveCartItem(item.productVariantId),
                                    );
                                  },
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    );
                  }
                }
                return const SizedBox.shrink();
              },
            ),
          ),

          BlocBuilder<VisitBloc, VisitState>(
            builder: (context, state) {
              if (state is VisitReady) return _buildFixedFooter(state);
              return const SizedBox.shrink();
            },
          ),
        ],
      ),
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
              onPressed: () => _validateAndSubmitSmart(state),
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

  // --- النافذة السفلية للبحث الذكي والحي المضيئة ---
  void _showProductSearch(List<ProductModel> catalog) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) {
        return ClipRRect(
          borderRadius: const BorderRadius.vertical(top: Radius.circular(30)),
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 25, sigmaY: 25),
            child: Directionality(
              textDirection: TextDirection.rtl,
              child: StatefulBuilder(
                builder: (context, setModalState) {
                  String searchQuery = '';
                  final filteredCatalog =
                      catalog
                          .where(
                            (p) => p.name.toLowerCase().contains(
                              searchQuery.toLowerCase(),
                            ),
                          )
                          .toList();

                  return Container(
                    height: MediaQuery.of(context).size.height * 0.7,
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(
                        alpha: 0.65,
                      ), // خلفية بيضاء زجاجية
                      borderRadius: const BorderRadius.vertical(
                        top: Radius.circular(30),
                      ),
                      border: Border.all(
                        color: Colors.white.withValues(alpha: 0.8),
                        width: 1.5,
                      ),
                    ),
                    child: Column(
                      children: [
                        Container(
                          width: 50,
                          height: 5,
                          decoration: BoxDecoration(
                            color: Colors.grey.withValues(alpha: 0.4),
                            borderRadius: BorderRadius.circular(5),
                          ),
                        ),
                        const SizedBox(height: 20),
                        const Text(
                          'اختر المنتج للزيارة',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            color: Color(0xFF212121),
                          ),
                        ),
                        const SizedBox(height: 20),

                        Container(
                          height: 50,
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.6),
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(
                              color: Colors.white.withValues(alpha: 0.9),
                            ),
                          ),
                          child: TextField(
                            onChanged:
                                (value) =>
                                    setModalState(() => searchQuery = value),
                            style: const TextStyle(
                              color: Color(0xFF212121),
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                            decoration: const InputDecoration(
                              hintText: 'بحث سريع عن صنف...',
                              hintStyle: TextStyle(
                                color: Color(0xFF9E9E9E),
                                fontSize: 14,
                              ),
                              prefixIcon: Icon(
                                Icons.search,
                                color: Color(0xFF757575),
                                size: 20,
                              ),
                              border: InputBorder.none,
                              contentPadding: EdgeInsets.symmetric(
                                vertical: 14,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 20),

                        Expanded(
                          child:
                              filteredCatalog.isEmpty
                                  ? const Center(
                                    child: Text(
                                      'لا توجد نتائج بحث.',
                                      style: TextStyle(
                                        color: Color(0xFF757575),
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                  )
                                  : ListView.builder(
                                    padding: const EdgeInsets.only(bottom: 20),
                                    itemCount: filteredCatalog.length,
                                    itemBuilder: (context, index) {
                                      final p = filteredCatalog[index];
                                      return Container(
                                        margin: const EdgeInsets.only(
                                          bottom: 12,
                                        ),
                                        decoration: BoxDecoration(
                                          color: Colors.white.withValues(
                                            alpha: 0.5,
                                          ), // كارت أبيض نقي شبه شفاف
                                          borderRadius: BorderRadius.circular(
                                            16,
                                          ),
                                          border: Border.all(
                                            color: Colors.white.withValues(
                                              alpha: 0.9,
                                            ),
                                          ),
                                        ),
                                        child: ListTile(
                                          contentPadding:
                                              const EdgeInsets.symmetric(
                                                horizontal: 16,
                                                vertical: 4,
                                              ),
                                          leading: Container(
                                            padding: const EdgeInsets.all(8),
                                            decoration: BoxDecoration(
                                              color: Colors.blue.withValues(
                                                alpha: 0.1,
                                              ),
                                              borderRadius:
                                                  BorderRadius.circular(8),
                                            ),
                                            child: const Icon(
                                              Icons.inventory_2_outlined,
                                              color: Colors.blue,
                                              size: 20,
                                            ),
                                          ),
                                          title: Text(
                                            p.name,
                                            style: const TextStyle(
                                              fontWeight: FontWeight.bold,
                                              color: Color(0xFF212121),
                                              fontSize: 15,
                                            ),
                                          ),
                                          subtitle: Text(
                                            'المتوفر بالسيارة: ${p.currentCartons} كرتونة | ${p.currentPacks} حبة',
                                            style: const TextStyle(
                                              color: Color(0xFF757575),
                                              fontSize: 13,
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                          trailing: const Icon(
                                            Icons.add_circle_outline,
                                            color: Colors.blue,
                                            size: 24,
                                          ),
                                          onTap: () {
                                            Navigator.pop(context);
                                            _showMagicDialog(
                                              CartItemModel(
                                                productVariantId: p.id,
                                                name: p.name,
                                                pricePerCarton:
                                                    p.pricePerCarton,
                                                pricePerPack: p.pricePerPack,
                                                packsPerCarton:
                                                    p.packsPerCarton,
                                                availableCartons:
                                                    p.currentCartons,
                                                availablePacks: p.currentPacks,
                                              ),
                                            );
                                          },
                                        ),
                                      );
                                    },
                                  ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ),
        );
      },
    );
  }

  // --- النافذة السحرية النيونية الذكية (Electric Navy Glass & Steppers) ---
  void _showMagicDialog(CartItemModel item) {
    final sCartons = TextEditingController(
      text: item.cartons > 0 ? item.cartons.toString() : '',
    );
    final sPacks = TextEditingController(
      text: item.packs > 0 ? item.packs.toString() : '',
    );
    final rCartons = TextEditingController(
      text: item.returnCartons > 0 ? item.returnCartons.toString() : '',
    );
    final rPacks = TextEditingController(
      text: item.returnPacks > 0 ? item.returnPacks.toString() : '',
    );

    // النوع الآن يسمح بـ null ولا يفرض التعجب (!)
    String? currentReturnType =
        item.returnType.isEmpty ? null : item.returnType;

    final smpCartons = TextEditingController(
      text: item.sampleCartons > 0 ? item.sampleCartons.toString() : '',
    );
    final smpPacks = TextEditingController(
      text: item.samplePacks > 0 ? item.samplePacks.toString() : '',
    );
    final smpReason = TextEditingController(text: item.sampleReason);

    // +++ متغيرات الطي (Accordion Logic) +++
    bool showReturns = (item.returnCartons > 0 || item.returnPacks > 0);
    bool showSamples =
        (item.sampleCartons > 0 ||
            item.samplePacks > 0 ||
            item.sampleReason.isNotEmpty);

    showGeneralDialog(
      context: context,
      barrierDismissible: true,
      barrierLabel: '',
      barrierColor: Colors.black.withValues(
        alpha: 0.7,
      ), // تعتيم قوي لإبراز النيون
      transitionDuration: const Duration(milliseconds: 300),
      pageBuilder: (context, animation, secondaryAnimation) {
        return Scaffold(
          backgroundColor: Colors.transparent,
          body: Center(
            child: SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20.0),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(30),
                  child: BackdropFilter(
                    filter: ImageFilter.blur(sigmaX: 25, sigmaY: 25),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        vertical: 24,
                        horizontal: 20,
                      ),
                      decoration: BoxDecoration(
                        // +++ تدرج كحلي كهربائي (Electric Navy) نقي وفخم +++
                        gradient: const LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: [
                            Color(0xE60A1128),
                            Color(0xE6142146),
                            Color(0xE6003F5C),
                          ],
                        ),
                        borderRadius: BorderRadius.circular(30),
                        border: Border.all(
                          color: Colors.white.withValues(alpha: 0.15),
                          width: 1.2,
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: Colors.cyan.withValues(alpha: 0.15),
                            blurRadius: 40,
                            offset: const Offset(0, 10),
                          ),
                        ],
                      ),
                      child: StatefulBuilder(
                        builder: (context, setDialogState) {
                          return Directionality(
                            textDirection: TextDirection.rtl,
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                // العنوان
                                Text(
                                  "إدخال بيانات: ${item.name}",
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.white,
                                  ),
                                ),
                                const SizedBox(height: 24),

                                // 1. قسم المبيعات (ظاهر دائماً)
                                _buildNeonSection(
                                  "المبيعات",
                                  Icons.shopping_cart_outlined,
                                  sCartons,
                                  sPacks,
                                ),
                                const SizedBox(height: 16),

                                // 2. قسم استبدال توالف (قابل للطي)
                                _buildExpandableHeader(
                                  title: "استبدال توالف",
                                  icon: Icons.warning_amber_rounded,
                                  isExpanded: showReturns,
                                  onTap: () {
                                    HapticFeedback.selectionClick();
                                    setDialogState(
                                      () => showReturns = !showReturns,
                                    );
                                  },
                                ),
                                AnimatedSize(
                                  duration: const Duration(milliseconds: 300),
                                  curve: Curves.easeInOut,
                                  child:
                                      showReturns
                                          ? Column(
                                            children: [
                                              const SizedBox(height: 12),
                                              Row(
                                                children: [
                                                  Expanded(
                                                    child: _buildStepperField(
                                                      rCartons,
                                                      "كراتين",
                                                    ),
                                                  ),
                                                  const SizedBox(width: 12),
                                                  Expanded(
                                                    child: _buildStepperField(
                                                      rPacks,
                                                      "حبات",
                                                    ),
                                                  ),
                                                ],
                                              ),
                                              const SizedBox(height: 12),
                                              // +++ الكي الجراحي: أزرار الراديو النيونية للتوالف +++
                                              _buildReturnTypeButtons(
                                                currentValue: currentReturnType,
                                                onChanged:
                                                    (val) => setDialogState(
                                                      () =>
                                                          currentReturnType =
                                                              val,
                                                    ),
                                              ),
                                              const SizedBox(height: 8),
                                            ],
                                          )
                                          : const SizedBox.shrink(),
                                ),
                                const Padding(
                                  padding: EdgeInsets.symmetric(vertical: 8.0),
                                  child: Divider(
                                    color: Colors.white12,
                                    height: 1,
                                  ),
                                ),

                                // 3. قسم العينات (قابل للطي)
                                _buildExpandableHeader(
                                  title: "العينات",
                                  icon: Icons.card_giftcard_outlined,
                                  isExpanded: showSamples,
                                  onTap: () {
                                    HapticFeedback.selectionClick();
                                    setDialogState(
                                      () => showSamples = !showSamples,
                                    );
                                  },
                                ),
                                AnimatedSize(
                                  duration: const Duration(milliseconds: 300),
                                  curve: Curves.easeInOut,
                                  child:
                                      showSamples
                                          ? Column(
                                            children: [
                                              const SizedBox(height: 12),
                                              Row(
                                                children: [
                                                  Expanded(
                                                    child: _buildStepperField(
                                                      smpCartons,
                                                      "كراتين",
                                                    ),
                                                  ),
                                                  const SizedBox(width: 12),
                                                  Expanded(
                                                    child: _buildStepperField(
                                                      smpPacks,
                                                      "حبات",
                                                    ),
                                                  ),
                                                ],
                                              ),
                                              const SizedBox(height: 12),
                                              _buildNeonTextField(
                                                hint:
                                                    "سبب صرف العينة (اختياري)",
                                                controller: smpReason,
                                              ),
                                              const SizedBox(height: 8),
                                            ],
                                          )
                                          : const SizedBox.shrink(),
                                ),
                                const SizedBox(height: 32),

                                // الأزرار السفلية
                                Row(
                                  children: [
                                    Expanded(
                                      flex: 2,
                                      child: GestureDetector(
                                        onTap: () {
                                          // اللوجيك الفولاذي + الاهتزاز عند الخطأ
                                          final int rCartonsVal =
                                              int.tryParse(rCartons.text) ?? 0;
                                          final int rPacksVal =
                                              int.tryParse(rPacks.text) ?? 0;

                                          if ((rCartonsVal > 0 ||
                                                  rPacksVal > 0) &&
                                              currentReturnType == null) {
                                            HapticFeedback.heavyImpact(); // اهتزاز قوي للتنبيه
                                            ScaffoldMessenger.of(
                                              context,
                                            ).showSnackBar(
                                              const SnackBar(
                                                content: Text(
                                                  'الرجاء تحديد نوع التلف للمرتجعات!',
                                                ),
                                                backgroundColor: Colors.red,
                                              ),
                                            );
                                            if (!showReturns) {
                                              setDialogState(
                                                () => showReturns = true,
                                              ); // توسيع تلقائي
                                            }
                                            return;
                                          }

                                          HapticFeedback.mediumImpact(); // اهتزاز نجاح
                                          final updatedItem = item.copyWith(
                                            cartons:
                                                int.tryParse(sCartons.text) ??
                                                0,
                                            packs:
                                                int.tryParse(sPacks.text) ?? 0,
                                            returnCartons: rCartonsVal,
                                            returnPacks: rPacksVal,
                                            returnType: currentReturnType,
                                            sampleCartons:
                                                int.tryParse(smpCartons.text) ??
                                                0,
                                            samplePacks:
                                                int.tryParse(smpPacks.text) ??
                                                0,
                                            sampleReason: smpReason.text,
                                          );
                                          _hasChanges = true;
                                          _visitBloc.add(
                                            AddOrUpdateCartItem(updatedItem),
                                          );
                                          Navigator.pop(context);
                                        },
                                        child: Container(
                                          height: 55,
                                          decoration: BoxDecoration(
                                            borderRadius: BorderRadius.circular(
                                              16,
                                            ),
                                            gradient: const LinearGradient(
                                              colors: [
                                                Color(0xFF00E5FF),
                                                Color(0xFF1200FF),
                                              ],
                                            ), // تدرج نيوني ساطع للزر
                                            boxShadow: [
                                              BoxShadow(
                                                color: const Color(
                                                  0xFF00E5FF,
                                                ).withValues(alpha: 0.4),
                                                blurRadius: 15,
                                                offset: const Offset(0, 5),
                                              ),
                                            ],
                                          ),
                                          child: const Center(
                                            child: Text(
                                              "اعتماد الصنف",
                                              style: TextStyle(
                                                color: Colors.white,
                                                fontWeight: FontWeight.bold,
                                                fontSize: 16,
                                              ),
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                    Expanded(
                                      child: Center(
                                        child: TextButton(
                                          onPressed: () {
                                            HapticFeedback.selectionClick();
                                            Navigator.pop(context);
                                          },
                                          child: const Text(
                                            "إلغاء",
                                            style: TextStyle(
                                              fontSize: 16,
                                              fontWeight: FontWeight.bold,
                                              color: Colors.white60,
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  // --- دوال بناء العناصر الكحلية النيونية ---
  Widget _buildExpandableHeader({
    required String title,
    required IconData icon,
    required bool isExpanded,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 4.0),
        child: Row(
          children: [
            Icon(icon, size: 20, color: Colors.cyanAccent), // أيقونات نيون
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
            ),
            const Spacer(),
            Icon(
              isExpanded
                  ? Icons.keyboard_arrow_up_rounded
                  : Icons.keyboard_arrow_down_rounded,
              color: Colors.white54,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNeonSection(
    String title,
    IconData icon,
    TextEditingController cController,
    TextEditingController pController,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 20, color: Colors.cyanAccent),
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(child: _buildStepperField(cController, "كراتين")),
            const SizedBox(width: 12),
            Expanded(child: _buildStepperField(pController, "حبات")),
          ],
        ),
      ],
    );
  }

  // +++ حقل الإدخال المزود بأزرار + و - (Stepper) +++
  Widget _buildStepperField(TextEditingController controller, String hint) {
    return Container(
      height: 48,
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.15)),
      ),
      child: Row(
        children: [
          // زر الناقص (-)
          InkWell(
            onTap: () {
              HapticFeedback.lightImpact();
              int current = int.tryParse(controller.text) ?? 0;
              if (current > 0) controller.text = (current - 1).toString();
            },
            borderRadius: const BorderRadius.horizontal(
              right: Radius.circular(16),
            ),
            child: SizedBox(
              width: 35,
              child: const Center(
                child: Icon(Icons.remove, color: Colors.white60, size: 20),
              ),
            ),
          ),
          Container(width: 1, color: Colors.white.withValues(alpha: 0.1)),
          // الحقل النصي
          Expanded(
            child: TextFormField(
              controller: controller,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontWeight: FontWeight.bold,
                color: Colors.white,
                fontSize: 18,
              ),
              decoration: InputDecoration(
                hintText: hint,
                hintStyle: const TextStyle(color: Colors.white38, fontSize: 13),
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ),
          Container(width: 1, color: Colors.white.withValues(alpha: 0.1)),
          // زر الزائد (+)
          InkWell(
            onTap: () {
              HapticFeedback.lightImpact();
              int current = int.tryParse(controller.text) ?? 0;
              controller.text = (current + 1).toString();
            },
            borderRadius: const BorderRadius.horizontal(
              left: Radius.circular(16),
            ),
            child: SizedBox(
              width: 35,
              child: const Center(
                child: Icon(Icons.add, color: Colors.cyanAccent, size: 20),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNeonTextField({
    required String hint,
    required TextEditingController controller,
  }) {
    return Container(
      height: 48,
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.15)),
      ),
      child: TextFormField(
        controller: controller,
        textAlign: TextAlign.center,
        style: const TextStyle(
          fontWeight: FontWeight.bold,
          color: Colors.white,
          fontSize: 15,
        ),
        decoration: InputDecoration(
          hintText: hint,
          hintStyle: const TextStyle(color: Colors.white38, fontSize: 13),
          border: InputBorder.none,
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 12,
            vertical: 12,
          ),
        ),
      ),
    );
  }

  // +++ أزرار اختيار نوع التلف السريعة بدلاً من القائمة المنسدلة +++
  Widget _buildReturnTypeButtons({
    required String? currentValue,
    required Function(String) onChanged,
  }) {
    return Row(
      children: [
        Expanded(
          child: GestureDetector(
            onTap: () {
              HapticFeedback.selectionClick();
              onChanged('Factory_Defect');
            },
            child: Container(
              height: 45,
              decoration: BoxDecoration(
                color:
                    currentValue == 'Factory_Defect'
                        ? Colors.cyan.withValues(alpha: 0.2)
                        : Colors.white.withValues(alpha: 0.03),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color:
                      currentValue == 'Factory_Defect'
                          ? Colors.cyanAccent
                          : Colors.white.withValues(alpha: 0.1),
                ),
              ),
              child: Center(
                child: Text(
                  "تالف مصنع",
                  style: TextStyle(
                    color:
                        currentValue == 'Factory_Defect'
                            ? Colors.cyanAccent
                            : Colors.white60,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: GestureDetector(
            onTap: () {
              HapticFeedback.selectionClick();
              onChanged('Expired');
            },
            child: Container(
              height: 45,
              decoration: BoxDecoration(
                color:
                    currentValue == 'Expired'
                        ? Colors.pinkAccent.withValues(alpha: 0.2)
                        : Colors.white.withValues(alpha: 0.03),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color:
                      currentValue == 'Expired'
                          ? Colors.pinkAccent
                          : Colors.white.withValues(alpha: 0.1),
                ),
              ),
              child: Center(
                child: Text(
                  "إكسباير",
                  style: TextStyle(
                    color:
                        currentValue == 'Expired'
                            ? Colors.pinkAccent
                            : Colors.white60,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    );
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
    bool hasReturns = state.cart.any(
      (i) => i.returnCartons > 0 || i.returnPacks > 0,
    );
    bool hasSamples = state.cart.any(
      (i) => i.sampleCartons > 0 || i.samplePacks > 0,
    );

    if (hasSales) {
      finalOutcome = 'Sale';
    } else if (hasReturns || hasSamples || debtPaidEntered > 0) {
      finalOutcome = 'NoSale';
    } else if (state.cart.isEmpty && cashEntered == 0 && debtPaidEntered == 0) {
      // السلة فارغة تماماً، تظهر نافذة التأجيل
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
