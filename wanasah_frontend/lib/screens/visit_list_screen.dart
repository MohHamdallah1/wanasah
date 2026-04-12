import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart'; // +++ ربط الشاشة بالـ BLoC
import 'dart:developer' as developer;
import 'visit_screen.dart';
import '../repositories/sync_repository.dart';
import 'package:wanasah_frontend/screens/add_shop_screen.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:map_launcher/map_launcher.dart';
import 'package:dio/dio.dart';

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

  final List<bool> _isSelected = [true, false, false];
  final List<String> _filterValues = ['All', 'Completed', 'Pending'];
  bool _isOnBreak = false;

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
    _checkBreakStatus();
  }

  Future<void> _checkBreakStatus() async {
    final breakStr = await const FlutterSecureStorage().read(
      key: 'is_on_break',
    );
    if (mounted) setState(() => _isOnBreak = breakStr == 'true');
  }

  @override
  void dispose() {
    _tabController.dispose();
    _visitListBloc
        .close(); // +++ الدرع الواقي: إغلاق البلوك لمنع تسريب الذاكرة +++
    super.dispose();
  }

  // +++ دالة المزامنة إجبارية مع السيرفر +++
  Future<void> _forceSync() async {
    developer.log('Forcing sync from API...');
    try {
      await SyncRepository().syncDown();
    } on DioException catch (_) {
      developer.log('Offline during refresh, ignoring syncDown error.');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('أنت أوفلاين، نعرض البيانات المحلية.'),
            backgroundColor: Colors.orange,
          ),
        );
      }
    }
    _visitListBloc.add(LoadVisitsEvent()); // تحديث القائمة بعد السحب
  }

  @override
  Widget build(BuildContext context) {
    return BlocProvider.value(
      value: _visitListBloc,
      child: BlocBuilder<VisitListBloc, VisitListState>(
        builder: (context, state) {
          if (state is VisitListLoading) {
            return const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            );
          }

          if (state is VisitListError) {
            return Scaffold(
              body: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      state.message,
                      style: const TextStyle(color: Colors.red),
                    ),
                    const SizedBox(height: 10),
                    ElevatedButton(
                      onPressed: _forceSync,
                      child: const Text('إعادة المحاولة'),
                    ),
                  ],
                ),
              ),
            );
          }

          if (state is VisitListLoaded) {
            bool isEmergencyActive = _tabController.index == 1;

            // +++ الحماية النوعية (VisitModel بدلاً من dynamic) +++
            final List<VisitModel> currentTabVisits =
                state.allVisits.where((v) {
                  return isEmergencyActive ? v.isEmergency : !v.isEmergency;
                }).toList();

            int currentTotal = currentTabVisits.length;
            int currentCompleted =
                currentTabVisits.where((v) => v.status == 'Completed').length;
            int currentPending =
                currentTabVisits.where((v) => v.status == 'Pending').length;

            return Scaffold(
              appBar: AppBar(
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
                  labelStyle: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 15,
                  ),
                  tabs: [
                    const Tab(icon: Icon(Icons.route), text: 'جولة اليوم 📍'),
                    Tab(
                      icon: const Icon(Icons.warning_amber_rounded),
                      text:
                          'طلبات عاجلة 🚨 (${state.allVisits.where((v) => v.isEmergency).length})',
                    ),
                  ],
                ),
              ),
              body: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      vertical: 8.0,
                      horizontal: 8.0,
                    ),
                    child: ToggleButtons(
                      isSelected: _isSelected,
                      onPressed: (int index) {
                        setState(() {
                          for (int i = 0; i < _isSelected.length; i++) {
                            _isSelected[i] = i == index;
                          }
                        });
                        // +++ توجيه أمر الفلترة للعقل المدبر (BLoC) +++
                        _visitListBloc.add(
                          FilterVisitsEvent(_filterValues[index]),
                        );
                      },
                      borderRadius: BorderRadius.circular(8.0),
                      constraints: BoxConstraints(
                        minHeight: 40.0,
                        minWidth:
                            (MediaQuery.of(context).size.width - 32) / 3.1,
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
                  Expanded(
                    child: TabBarView(
                      controller: _tabController,
                      children: [
                        _buildListView(
                          state.filteredVisits
                              .where((v) => !v.isEmergency)
                              .toList(),
                          isEmergencyTab: false,
                          currentFilter: state.currentFilter,
                        ),
                        _buildListView(
                          state.filteredVisits
                              .where((v) => v.isEmergency)
                              .toList(),
                          isEmergencyTab: true,
                          currentFilter: state.currentFilter,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              floatingActionButton: FloatingActionButton(
                onPressed: () async {
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

                  final result = await Navigator.push<bool>(
                    context,
                    MaterialPageRoute(
                      builder: (context) => const AddShopScreen(),
                    ),
                  );

                  if (!context.mounted) return;
                  if (result == true) {
                    _forceSync();
                  }
                },
                tooltip: 'إضافة محل جديد',
                child: const Icon(Icons.add),
              ),
            );
          }
          return const SizedBox.shrink();
        },
      ),
    );
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
        padding: const EdgeInsets.all(12.0),
        itemCount: visitsList.length,
        itemBuilder: (context, index) {
          final VisitModel visit = visitsList[index];

          final String shopName = visit.shopName;
          final String visitStatus = visit.status;

          String statusInArabic;
          if (visitStatus == 'Completed') {
            statusInArabic = 'مكتملة';
          } else if (visitStatus == 'Pending') {
            statusInArabic = 'قيد الانتظار';
          } else {
            statusInArabic = visitStatus;
          }

          final double shopBalance = visit.shopBalance;
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

                // +++ سد ثغرة البيانات الميتة (Navigation Trap) عبر إرسال حدث للـ BLoC +++
                if (mounted) {
                  developer.log(
                    'Returned from VisitScreen, triggering Bloc LoadVisitsEvent...',
                  );
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
