import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart'; // +++ ربط الشاشة بالـ BLoC
import 'dart:async'; // +++ بصمة الـ Elite: لدعم الـ Completer +++
import 'dart:developer' as developer;
import 'visit_screen.dart';
import 'package:wanasah_frontend/screens/add_shop_screen.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:map_launcher/map_launcher.dart';

import '../models/visit_model.dart'; // +++ الحماية النوعية
import '../blocs/visit_list/visit_list_bloc.dart'; // +++ العقل المدبر
import '../blocs/visit_list/visit_list_event.dart';
import '../blocs/visit_list/visit_list_state.dart';

class VisitListScreen extends StatefulWidget {
  final int driverId;
  const VisitListScreen({required this.driverId, super.key});

  @override
  State<VisitListScreen> createState() => _VisitListScreenState();
}

class _VisitListScreenState extends State<VisitListScreen>
    with SingleTickerProviderStateMixin {
  // --- متغيرات الحالة الخاصة بالواجهة فقط (Dumb UI) ---
  late TabController _tabController;
  late VisitListBloc _visitListBloc; // +++ العقل المدبر الخاص بالشاشة +++

  final List<String> _filterValues = ['All', 'Completed', 'Pending'];

  @override
  void initState() {
    super.initState();
    _visitListBloc = VisitListBloc(); // إنشاء البلوك محلياً لحماية الشاشة
    _visitListBloc.add(LoadVisitsEvent()); // الأمر الأول لجلب البيانات

    _tabController = TabController(length: 2, vsync: this);
    _tabController.addListener(() {
      if (mounted && !_tabController.indexIsChanging) {
        setState(() {});
      }
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    _visitListBloc
        .close(); // +++ الدرع الواقي: إغلاق البلوك لمنع تسريب الذاكرة +++
    super.dispose();
  }

  // +++ بصمة الـ Elite Senior: إجبار الـ RefreshIndicator على الانتظار بالطريقة التفاعلية الآمنة للذاكرة +++
  Future<void> _forceSync() async {
    developer.log('Forcing sync via BLoC...');
    _visitListBloc.add(const RefreshVisitsEvent());
    
    try {
      // انتظار وصول حالة النهاية (نجاح أو خطأ) بحد أقصى 10 ثوانٍ بدون ترك Listeners معلقة
      await _visitListBloc.stream
          .firstWhere((state) => state is VisitListLoaded || state is VisitListError)
          .timeout(const Duration(seconds: 10));
    } catch (_) {
      developer.log('[VisitListScreen] Sync indicator timeout safely aborted.');
    }
  }

  @override
  Widget build(BuildContext context) {
    return BlocProvider.value(
      value: _visitListBloc,
      child: BlocListener<VisitListBloc, VisitListState>(
        listener: (context, state) {
          if (state is VisitListError) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(state.message),
                backgroundColor: state.message.contains('انقطع') ? Colors.orange : Colors.red,
              ),
            );
          }
        },
        child: BlocBuilder<VisitListBloc, VisitListState>(
        builder: (context, state) {
          // استخراج المتغيرات الأساسية للهيكل لتبقى ثابتة (السر الذي يمنع الوميض)
          int currentTotal = 0;
          int currentCompleted = 0;
          int currentPending = 0;
          int emgCount = 0;
          List<VisitModel> currentTabVisits = [];
          String currentFilter = 'All';

          if (state is VisitListLoaded) {
            bool isEmergencyActive = _tabController.index == 1;
            emgCount = state.allVisits.where((v) => v.isEmergency).length;
            currentTabVisits = state.allVisits.where((v) => isEmergencyActive ? v.isEmergency : !v.isEmergency).toList();
            currentTotal = currentTabVisits.length;
            currentCompleted = currentTabVisits.where((v) => v.status == 'Completed').length;
            currentPending = currentTabVisits.where((v) => v.status == 'Pending').length;
            currentFilter = state.currentFilter;
          }

          return Scaffold(
            // +++  لظاهرة الأشباح: إعطاء لون صلب يمنع شفافية الشاشات أثناء التنقل +++
            backgroundColor: Colors.grey.shade50,
            appBar: AppBar(
              backgroundColor: Colors.grey.shade50,
              elevation: 0,
              surfaceTintColor: Colors.transparent,
              title: const Text('قائمة المحلات'),
              centerTitle: true,
              actions: [
                IconButton(
                  onPressed: _forceSync,
                  icon: const Icon(Icons.refresh),
                  tooltip: 'تحديث القائمة',
                ),
              ],
              bottom: TabBar(
                controller: _tabController,
                labelColor: const Color.fromARGB(255, 17, 5, 5),
                unselectedLabelColor: const Color.fromARGB(179, 14, 7, 7),
                indicatorColor: const Color.fromARGB(255, 73, 16, 16),
                indicatorWeight: 4,
                labelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
                tabs: [
                  const Tab(text: 'جولة اليوم 📍'),
                  Tab(text: 'طلبات عاجلة 🚨 ($emgCount)'),
                ],
              ),
            ),
            floatingActionButton: FloatingActionButton(
              onPressed: () async {
                const storage = FlutterSecureStorage();
                // +++  لاختراق الاستراحة: فحص حي (Dynamic Check) للحالة من الخزنة مباشرة +++
                final breakStr = await storage.read(key: 'is_on_break');
                if (!context.mounted) return;
                
                if (breakStr == 'true') {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('أنت في وقت الاستراحة.'), backgroundColor: Colors.orange));
                  return;
                }
                
                String? authStr = await storage.read(key: 'is_authorized');
                if (!context.mounted) return;
                if (authStr != 'true') {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('غير مصرح لك بإضافة محلات.'), backgroundColor: Colors.orange));
                  return;
                }
                final result = await Navigator.push<bool>(context, MaterialPageRoute(builder: (context) => const AddShopScreen()));
                if (!context.mounted) return;
                if (result == true) _forceSync();
              },
              tooltip: 'إضافة محل جديد',
              child: const Icon(Icons.add),
            ),
            body: _buildBodyContent(state, currentTotal, currentCompleted, currentPending, currentTabVisits, currentFilter),
          );
        },
      ),
      ),
    );
  }

  // +++ دالة مساعدة جديدة تبني المحتوى الداخلي فقط بدون المساس بالـ Scaffold +++
  Widget _buildBodyContent(VisitListState state, int currentTotal, int currentCompleted, int currentPending, List<VisitModel> currentTabVisits, String currentFilter) {
    if (state is VisitListLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (state is VisitListError) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(state.message, style: const TextStyle(color: Colors.red)),
            const SizedBox(height: 10),
            ElevatedButton(onPressed: _forceSync, child: const Text('إعادة المحاولة')),
          ],
        ),
      );
    }
    if (state is VisitListLoaded) {
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 8.0),
            child: ToggleButtons(
              // +++  لـ Bug 2: قراءة حالة الفلتر من الـ BLoC بدلاً من المتغير الوهمي +++
              isSelected: _filterValues.map((filter) => filter == currentFilter).toList(),
              onPressed: (int index) {
                _visitListBloc.add(FilterVisitsEvent(_filterValues[index]));
              },
              borderRadius: BorderRadius.circular(8.0),
              constraints: BoxConstraints(minHeight: 40.0, minWidth: (MediaQuery.of(context).size.width - 32) / 3.1),
              children: <Widget>[
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Text('الكل ($currentTotal)')),
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Text('المكتملة ($currentCompleted)')),
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Text('المتبقية ($currentPending)')),
              ],
            ),
          ),
          const Divider(height: 1, thickness: 1),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _buildListView(state.filteredVisits.where((v) => !v.isEmergency).toList(), isEmergencyTab: false, currentFilter: currentFilter),
                _buildListView(state.filteredVisits.where((v) => v.isEmergency).toList(), isEmergencyTab: true, currentFilter: currentFilter),
              ],
            ),
          ),
        ],
      );
    }
    return const SizedBox.shrink();
  }

  // --- دالة مساعدة لبناء القائمة بتصميم "البطاقات" الحديث والحماية النوعية ---
  Widget _buildListView(
    List<VisitModel> visitsList, {
    required bool isEmergencyTab,
    required String currentFilter,
  }) {
    if (visitsList.isEmpty) {
      String emptyMessage =
          isEmergencyTab
              ? 'لا يوجد طلبات طارئة حالياً 🚨'
              : 'لا توجد زيارات مجدولة لك حالياً 📍';
      if (currentFilter == 'Pending') {
        emptyMessage =
            isEmergencyTab
                ? 'لا يوجد طلبات طارئة متبقية.'
                : 'لا توجد زيارات متبقية.';
      } else if (currentFilter == 'Completed') {
        emptyMessage =
            isEmergencyTab
                ? 'لم تقم بإكمال أي طلب طارئ بعد.'
                : 'لم تقم بإكمال أي زيارة بعد.';
      }
      return RefreshIndicator(
        onRefresh: _forceSync,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
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
      onRefresh: _forceSync,
      child: ListView.builder(
        key: PageStorageKey<String>(
          'visitListScroll_${isEmergencyTab ? "emg" : "norm"}',
        ),
        physics: const AlwaysScrollableScrollPhysics(),
        // +++ درع الفاب (FAB Shield): حشو سفلي لمنع تغطية آخر عنصر في القائمة بواسطة الزر العائم +++
        padding: const EdgeInsets.only(top: 12.0, left: 12.0, right: 12.0, bottom: 80.0),
        itemCount: visitsList.length,
        itemBuilder: (context, index) {
          final VisitModel visit = visitsList[index];

          final String shopName = visit.shopName;
          final String visitStatus = visit.status;

          // +++   توضيح الحالة الفعلية للزيارات التي تمت محاولتها ولم تكتمل بمبيعات +++
          String statusInArabic;
          if (visitStatus == 'Completed') {
            statusInArabic = 'مكتملة';
          } else if (visitStatus == 'Pending' && visit.outcome.isNotEmpty) {
            statusInArabic = visit.outcome == 'Postponed' ? 'مؤجلة' : (visit.outcome == 'NoSale' ? 'بدون بيع' : 'محاولة سابقة');
          } else if (visitStatus == 'Pending') {
            statusInArabic = 'قيد الانتظار';
          } else {
            statusInArabic = visitStatus;
          }

          final double shopBalance = visit.shopBalance;
          // +++ الانصياع لقاعدة أبو علي المعمارية: التطبيق مرآة للوحة التحكم (Source of Truth) +++
          final String sequenceDisplay = visit.sequence.toString();

          bool isCompleted = visitStatus == 'Completed';
          bool isAttempted =
              visitStatus == 'Pending' && visit.outcome.isNotEmpty;

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

          return Card(
            // +++  (VLS-4): استخدام معرّف الزيارة لمنع كراش الواجهة إذا تكرر المحل +++
            key: ValueKey(visit.id),
            elevation: isCompleted ? 0 : 2,
            margin: const EdgeInsets.only(bottom: 12.0),
            color: cardBgColor,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(color: cardBorderColor, width: 1.2),
            ),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              splashColor: Colors.transparent,
              highlightColor: Colors.transparent,
              onTap: () async {
                // +++  لاختراق الاستراحة: فحص حي للحالة +++
                final breakStr = await const FlutterSecureStorage().read(key: 'is_on_break');
                
                // +++ درع الـ BuildContext الشامل لحماية الشاشة بالكامل (إصلاح خطأ سطر 364) +++
                if (!context.mounted) return; 

                if (breakStr == 'true') {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.'),
                      backgroundColor: Colors.orange,
                    ),
                  );
                  return;
                }

                developer.log(
                  'Navigating to VisitScreen for visit ID: ${visit.id}',
                );

                await Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder:
                        (context) => VisitScreen(
                          visitId: visit.id,
                          shopName: shopName,
                          shopBalance: shopBalance,
                          visitStatus: visitStatus,
                        ),
                  ),
                );

                // +++   قراءة محلية فورية (O(1)) بدون تأخير وبدون إرسال طلب وهمي للسيرفر +++
                if (mounted) {
                  developer.log('Returned from VisitScreen, loading local data instantly...');
                  _visitListBloc.add(LoadVisitsEvent());
                }
              },
              child: Padding(
                padding: const EdgeInsets.all(12.0),
                child: Row(
                  children: [
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
                    IconButton(
                      icon: const Icon(
                        Icons.map_outlined,
                        color: Colors.blue,
                        size: 28,
                      ),
                      tooltip: 'عرض الموقع',
                      onPressed: () async {
                        final double? lat = visit.latitude;
                        final double? lng = visit.longitude;
                        final String? link = visit.locationLink;

                        try {
                          // +++  لـ Bug 3: حماية الكراش وتجاهل إحداثيات المحيط الأطلسي (0.0) +++
                          if (lat != null && lng != null && lat != 0.0 && lng != 0.0) {
                            final bool isGoogleMapsAvailable = await MapLauncher.isMapAvailable(MapType.google) ?? false;
                            
                            if (isGoogleMapsAvailable) {
                              await MapLauncher.showMarker(
                                mapType: MapType.google,
                                coords: Coords(lat, lng),
                                title: shopName,
                              );
                            } else {
                              // سقوط آمن: فتح الخرائط المتوفرة أو رمي خطأ إذا لم يوجد شيء
                              final availableMaps = await MapLauncher.installedMaps;
                              if (availableMaps.isNotEmpty) {
                                await availableMaps.first.showMarker(
                                  coords: Coords(lat, lng),
                                  title: shopName,
                                );
                              } else {
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('لا يوجد تطبيق خرائط مثبت على الجهاز')));
                              }
                            }
                          } else if (link != null && link.trim().isNotEmpty) {
                            // +++  لتنظيف الروابط لضمان عدم ضرب الكراش على أجهزة الأندرويد +++
                            String cleanLink = link.trim();
                            if (!cleanLink.startsWith('http://') && !cleanLink.startsWith('https://')) {
                              cleanLink = 'https://$cleanLink';
                            }
                            final Uri url = Uri.parse(cleanLink);
                            final bool launched = await launchUrl(url, mode: LaunchMode.externalApplication);
                            // +++ إصلاح خطأ 481: فحص הـ Context الخاص بالبطاقة وليس الشاشة +++
                            if (!context.mounted) return; 
                            if (!launched) {
                              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('لا يمكن فتح الرابط')));
                            }
                          } else {
                            // +++ إصلاح خطأ 489: فحص הـ Context الخاص بالبطاقة +++
                            if (!context.mounted) return; 
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('لا يتوفر موقع مسجل لهذا المحل')));
                          }
                        } catch (e) {
                          if (!context.mounted) return; 
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('خطأ في الخريطة: ${e.toString()}')));
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
