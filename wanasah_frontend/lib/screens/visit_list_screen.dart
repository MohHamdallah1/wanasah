import 'package:flutter/material.dart';
import 'dart:developer' as developer;
import 'visit_screen.dart'; // نحتاج هذا للانتقال
import '../core/db/local_database.dart';
import '../repositories/sync_repository.dart';
import 'package:wanasah_frontend/screens/add_shop_screen.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:url_launcher/url_launcher.dart'; // +++ للخرائط +++
import 'package:map_launcher/map_launcher.dart'; // +++ للخرائط +++

class VisitListScreen extends StatefulWidget {
  final int driverId;
  const VisitListScreen({required this.driverId, super.key});

  @override
  State<VisitListScreen> createState() => _VisitListScreenState();
}

class _VisitListScreenState extends State<VisitListScreen>
    with SingleTickerProviderStateMixin {
  // --- متغيرات الحالة ---
  late TabController _tabController;
  bool _isLoading = true;
  List<dynamic> _allVisits = [];
  List<dynamic> _filteredVisits = [];
  String? _error;
  String? _selectedStatusFilter; // <-- فقط عرف المتغير بدون = null
  // ignore: prefer_final_fields
  List<bool> _isSelected = [true, false, false]; // الكل, المكتملة, المتبقية
  final List<String?> _filterValues = [null, 'Completed', 'Pending'];
  bool _isOnBreak = false;
  // --- نهاية متغيرات الحالة ---

  @override
  void initState() {
    super.initState();
    // إعداد متحكم التبويبات وربطه بتحديث الشاشة لتتغير العدادات فوراً عند النقر
    _tabController = TabController(length: 2, vsync: this);
    _tabController.addListener(() {
      if (mounted) setState(() {});
    });
    _fetchVisits();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  // --- دالة جلب البيانات (معمارية Offline-First من الخزنة المحلية) ---
  Future<void> _fetchVisits({bool forceSync = false}) async {
    if (!mounted) return;

    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      // 1. المزامنة مع السيرفر فقط عند الطلب (سحب الشاشة أو إضافة محل)
      if (forceSync) {
        developer.log('Forcing sync from API...');
        await SyncRepository().syncDown();
      }

      // 2. القراءة الصاروخية من قاعدة البيانات المحلية (SQLite)
      final localVisits = await LocalDatabase.instance.getVisits();

      // 3. قراءة حالة الاستراحة المحفوظة مسبقاً من الذاكرة
      final breakStr = await const FlutterSecureStorage().read(
        key: 'is_on_break',
      );

      if (!mounted) return;

      // 4. عرض البيانات فوراً للمندوب
      setState(() {
        _isOnBreak = breakStr == 'true';
        _allVisits = localVisits;
        _applyFilter();
        _isLoading = false;
        _error = null;
      });
      developer.log('Loaded ${localVisits.length} visits from Local DB.');
    } catch (error) {
      developer.log('Error fetching local visits: $error');
      if (!mounted) return;
      setState(() {
        _error = 'حدث خطأ أثناء تحميل البيانات المخبأة.';
        _isLoading = false;
      });
    }
  }
  // --- نهاية الدالة المعدلة ---

  // --- دالة تطبيق الفلترة محلياً ---
  void _applyFilter() {
    if (_selectedStatusFilter == null) {
      // الكل
      _filteredVisits = List.from(_allVisits);
    } else {
      // Pending or Completed
      _filteredVisits =
          _allVisits.where((visit) {
            return visit is Map &&
                visit['visit_status'] == _selectedStatusFilter;
          }).toList();
    }
    // لا نحتاج setState هنا لأنها تُستدعى من مكان آخر
  }

  @override
  Widget build(BuildContext context) {
    // +++ فصل العدادات ديناميكياً بناءً على التبويب النشط لحل لغز الترقيم الخاطئ +++
    bool isEmergencyActive = _tabController.index == 1;

    final List<dynamic> currentTabVisits =
        _allVisits.where((v) {
          if (v == null || v is! Map) return false;
          final isEmerg =
              v['is_emergency'] == true ||
              v['is_emergency'] == 1 ||
              v['is_emergency'] == 'true';
          return isEmergencyActive ? isEmerg : !isEmerg;
        }).toList();

    int currentTotal = currentTabVisits.length;
    int currentCompleted =
        currentTabVisits.where((v) => v['visit_status'] == 'Completed').length;
    int currentPending =
        currentTabVisits.where((v) => v['visit_status'] == 'Pending').length;
    // +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

    return Scaffold(
      appBar: AppBar(
        title: const Text('قائمة المحلات'),
        centerTitle: true,
        actions: [
          IconButton(
            // +++ إجبار المزامنة مع السيرفر عند الضغط اليدوي +++
            onPressed: () => _fetchVisits(forceSync: true),
            icon: const Icon(Icons.refresh),
            tooltip: 'تحديث القائمة',
          ),
        ],
        // +++ شريط التبويبات الحديث (تم إزالة const لحل خطأ الكومبايلر وربط المتحكم) +++
        bottom: TabBar(
          controller: _tabController,
          labelColor: const Color.fromARGB(255, 17, 5, 5),
          unselectedLabelColor: const Color.fromARGB(179, 14, 7, 7),
          indicatorColor: const Color.fromARGB(255, 73, 16, 16),
          indicatorWeight: 4,
          labelStyle: const TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 15,
          ),
          tabs: [
            const Tab(icon: Icon(Icons.route), text: 'جولة اليوم 📍'),
            Tab(
              icon: const Icon(Icons.warning_amber_rounded),
              text:
                  'طلبات عاجلة 🚨 (${_allVisits.where((v) => v != null && v is Map && (v['is_emergency'] == true || v['is_emergency'] == 1 || v['is_emergency'] == 'true')).length})',
            ),
          ],
        ),
        // ++++++++++++++++++++++++++++++
      ),
      body: Column(
        children: [
          // --- أزرار الفلترة مع الأعداد ---
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 8.0),
            child: ToggleButtons(
              isSelected: _isSelected,
              onPressed: (int index) {
                if (_isSelected[index]) return;
                setState(() {
                  for (int i = 0; i < _isSelected.length; i++) {
                    _isSelected[i] = i == index;
                  }
                  _selectedStatusFilter = _filterValues[index];
                  _applyFilter(); // تطبيق الفلتر محلياً
                });
              },
              borderRadius: BorderRadius.circular(8.0),
              constraints: BoxConstraints(
                minHeight: 40.0,
                minWidth: (MediaQuery.of(context).size.width - 32) / 3.1,
              ),
              children: <Widget>[
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Text('الكل ($currentTotal)'),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Text('المكتملة ($currentCompleted)'),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Text('المتبقية ($currentPending)'),
                ),
              ],
            ),
          ),
          const Divider(height: 1, thickness: 1),

          // --- عرض المحتوى (القائمة أو الرسائل الأخرى) ---
          Expanded(child: _buildContent()),
        ],
      ),
      // +++ إضافة الزر العائم هنا +++
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          // +++ الحماية المعمارية 1: فحص الاستراحة بشكل مستقل وأولاً +++
          if (_isOnBreak) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.',
                ),
                backgroundColor: Colors.orange,
              ),
            );
            return;
          }

          // +++ الحماية المعمارية 2: التحقق من الضوء الأخضر (الصلاحية) +++
          const storage = FlutterSecureStorage();
          String? authStr = await storage.read(key: 'is_authorized');

          if (!context.mounted) return;

          if (authStr != 'true') {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'غير مصرح لك بإضافة محلات حالياً. بانتظار تفعيل خط السير من الإدارة.',
                ),
                backgroundColor: Colors.orange,
              ),
            );
            return;
          }
          // ++++++++++++++++++++++++++++++++++++++++++++++

          if (!context.mounted) return; // الحماية قبل فتح الروتر
          // --- الكود الأصلي لفتح شاشة إضافة المحل ---
          final result = await Navigator.push<bool>(
            context,
            MaterialPageRoute(builder: (context) => const AddShopScreen()),
          );

          // الحماية السحرية الثانية: التأكد أن الشاشة موجودة بعد العودة من الإضافة
          if (!context.mounted) return;

          if (result == true) {
            developer.log('AddShopScreen closed with success, forcing sync...');
            // +++ جلب المحل الجديد من السيرفر وتحديث الخزنة +++
            _fetchVisits(forceSync: true);
          }
        },

        tooltip: 'إضافة محل جديد',
        child: const Icon(Icons.add),
      ),
    ); // +++ إغلاق Scaffold +++
  }

  Widget _buildContent() {
    // الأولوية لعرض الخطأ إن وجد
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                'حدث خطأ: $_error',
                style: const TextStyle(color: Colors.red),
              ),
              const SizedBox(height: 10),
              ElevatedButton(
                onPressed: _fetchVisits,
                child: const Text('إعادة المحاولة'),
              ),
            ],
          ),
        ),
      );
    }
    // ثم عرض مؤشر التحميل
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    // +++ فصل الزيارات بعد فلترتها مع حماية صارمة وتحويل ذكي للأنواع (Type Casting) +++
    final List<dynamic> normalVisits =
        _filteredVisits.where((v) {
          if (v == null || v is! Map) return false;
          // دعم كل أنواع الاستجابة (boolean, int, string) من السيرفر
          final isEmerg =
              v['is_emergency'] == true ||
              v['is_emergency'] == 1 ||
              v['is_emergency'] == 'true';
          return !isEmerg;
        }).toList();

    final List<dynamic> emergencyVisits =
        _filteredVisits.where((v) {
          if (v == null || v is! Map) return false;
          final isEmerg =
              v['is_emergency'] == true ||
              v['is_emergency'] == 1 ||
              v['is_emergency'] == 'true';
          return isEmerg;
        }).toList();

    // +++ عرض التبويبات مع ربطها بالمتحكم +++
    return TabBarView(
      controller: _tabController,
      children: [
        _buildListView(normalVisits, isEmergencyTab: false),
        _buildListView(emergencyVisits, isEmergencyTab: true),
      ],
    );
  }

  // --- دالة مساعدة لبناء القائمة بتصميم "البطاقات" الحديث ---
  Widget _buildListView(
    List<dynamic> visitsList, {
    required bool isEmergencyTab,
  }) {
    if (visitsList.isEmpty) {
      String emptyMessage =
          isEmergencyTab
              ? 'لا يوجد طلبات طارئة حالياً 🚨'
              : 'لا توجد زيارات مجدولة لك حالياً 📍';
      if (_selectedStatusFilter == 'Pending') {
        emptyMessage =
            isEmergencyTab
                ? 'لا يوجد طلبات طارئة متبقية.'
                : 'لا توجد زيارات متبقية.';
      } else if (_selectedStatusFilter == 'Completed') {
        emptyMessage =
            isEmergencyTab
                ? 'لم تقم بإكمال أي طلب طارئ بعد.'
                : 'لم تقم بإكمال أي زيارة بعد.';
      }
      return RefreshIndicator(
        onRefresh: () => _fetchVisits(forceSync: true),
        child: ListView(
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 50.0),
              child: Center(
                child: Text(
                  emptyMessage,
                  style: const TextStyle(
                    fontSize: 16,
                    color: Colors.grey,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => _fetchVisits(forceSync: true),
      child: ListView.builder(
        key: PageStorageKey<String>(
          'visitListScroll_${isEmergencyTab ? "emg" : "norm"}',
        ),
        padding: const EdgeInsets.all(12.0),
        itemCount: visitsList.length,
        itemBuilder: (context, index) {
          final visit = visitsList[index] as Map<String, dynamic>;

          final shopName = visit['shop_name'] ?? 'اسم المحل غير متوفر';
          final visitStatus = visit['visit_status'] ?? 'غير محدد';

          String statusInArabic;
          if (visitStatus == 'Completed') {
            statusInArabic = 'مكتملة';
          } else if (visitStatus == 'Pending') {
            statusInArabic = 'قيد الانتظار';
          } else {
            statusInArabic = visitStatus;
          }

          final shopBalance =
              double.tryParse(visit['shop_balance']?.toString() ?? '0.0') ??
              0.0;
          final bool hasNotes =
              visit['visit_notes'] != null &&
              visit['visit_notes'].toString().isNotEmpty;
          final int? sequence = visit['visit_sequence'];
          final String sequenceDisplay = sequence?.toString() ?? '-';

          bool isCompleted = visitStatus == 'Completed';
          bool isAttempted = visitStatus == 'Pending' && hasNotes;

          // --- تصميم الألوان والأيقونات الذكي ---
          IconData leadingIcon =
              isEmergencyTab ? Icons.warning_amber_rounded : Icons.storefront;
          Color iconColor = Colors.blueGrey;
          Color cardBorderColor = Colors.grey.shade300;
          Color cardBgColor =
              isEmergencyTab
                  ? Colors.red.shade50.withValues(alpha: 0.3)
                  : Colors.white;

          if (isCompleted) {
            leadingIcon = Icons.check_circle;
            iconColor = Colors.green;
            cardBorderColor = Colors.green.shade300;
            cardBgColor = Colors.green.shade50.withValues(alpha: 0.4);
          } else if (isAttempted) {
            leadingIcon = Icons.history;
            iconColor = Colors.orange;
            cardBorderColor = Colors.orange.shade300;
          } else if (isEmergencyTab) {
            iconColor = Colors.red.shade600;
            cardBorderColor = Colors.red.shade300;
            cardBgColor = Colors.red.shade50;
          }

          // --- البطاقة الحديثة (Modern Card) ---
          return Card(
            elevation: isCompleted ? 0 : 2,
            margin: const EdgeInsets.only(bottom: 12.0),
            color: cardBgColor,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(color: cardBorderColor, width: 1.2),
            ),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: () async {
                // +++ الحماية اللحظية من الاستراحة (Live Reactivity) +++
                if (_isOnBreak) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.',
                      ),
                      backgroundColor: Colors.orange,
                    ),
                  );
                  return;
                }

                // --- تم الاحتفاظ بالكود الأصلي للانتقال 100% لضمان عدم حدوث أي خلل ---
                final int visitId = visit['visit_id'] ?? 0;
                final String currentStatus = visitStatus;
                final double currentBalance = shopBalance;

                developer.log(
                  'Navigating to VisitScreen for visit ID: $visitId',
                );

                await Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder:
                        (context) => VisitScreen(
                          visitId: visitId,
                          shopName: shopName,
                          shopBalance: currentBalance,
                          visitStatus: currentStatus,
                        ),
                  ),
                );

                // +++ تحديث لحظي إجباري عند العودة من أي زيارة لضمان تحديث الأيقونات والحالة +++
                if (mounted) {
                  developer.log(
                    'Returned from VisitScreen, loading fast from local DB...',
                  );
                  // +++ تحديث الشاشة من الخزنة المحلية فقط وبسرعة +++
                  _fetchVisits(forceSync: false);
                }
                // -------------------------------------------------------------------
              },
              child: Padding(
                padding: const EdgeInsets.all(12.0),
                child: Row(
                  children: [
                    // الأيقونة داخل دائرة ملونة
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color:
                            isCompleted
                                ? Colors.green.shade100
                                : (isEmergencyTab
                                    ? Colors.red.shade100
                                    : Colors.blue.shade50),
                        shape: BoxShape.circle,
                      ),
                      child: Icon(leadingIcon, color: iconColor, size: 26),
                    ),
                    const SizedBox(width: 14),

                    // التفاصيل النصية
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '$sequenceDisplay. $shopName',
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Row(
                            children: [
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 4,
                                ),
                                decoration: BoxDecoration(
                                  color:
                                      isCompleted
                                          ? Colors.green
                                          : (isAttempted
                                              ? Colors.orange
                                              : Colors.blueGrey),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  statusInArabic,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 11,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Text(
                                'الذمة: ${shopBalance.toStringAsFixed(2)} د.أ',
                                style: TextStyle(
                                  color: Colors.grey.shade700,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),

                    // +++ زر الخريطة الذكي بدلاً من السهم الرمادي +++
                    IconButton(
                      icon: const Icon(
                        Icons.map_outlined,
                        color: Colors.blue,
                        size: 28,
                      ),
                      tooltip: 'عرض الموقع',
                      onPressed: () async {
                        final double? lat = visit['shop_latitude'];
                        final double? lng = visit['shop_longitude'];
                        final String? link = visit['shop_location_link'];

                        try {
                          if (lat != null && lng != null) {
                            await MapLauncher.showMarker(
                              mapType: MapType.google,
                              coords: Coords(lat, lng),
                              title: shopName,
                            );
                          } else if (link != null && link.trim().isNotEmpty) {
                            final Uri url = Uri.parse(link.trim());
                            if (!await launchUrl(
                              url,
                              mode: LaunchMode.externalApplication,
                            )) {
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                    content: Text('لا يمكن فتح الرابط'),
                                  ),
                                );
                              }
                            }
                          } else {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text(
                                    'لا يتوفر موقع مسجل لهذا المحل',
                                  ),
                                ),
                              );
                            }
                          }
                        } catch (e) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(
                                  'خطأ في الخريطة: ${e.toString()}',
                                ),
                              ),
                            );
                          }
                        }
                      },
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
