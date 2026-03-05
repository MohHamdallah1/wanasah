import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:developer' as developer;
import 'visit_screen.dart'; // نحتاج هذا للانتقال
import '../services/auth_utils.dart';
import 'package:wanasah_frontend/screens/add_shop_screen.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// تم حذف import 'package:flutter/services.dart'; لأنه غير مستخدم هنا <<<---

class VisitListScreen extends StatefulWidget {
  final int driverId;
  const VisitListScreen({required this.driverId, super.key});

  @override
  State<VisitListScreen> createState() => _VisitListScreenState();
}

class _VisitListScreenState extends State<VisitListScreen> {
  // --- متغيرات الحالة ---
  bool _isLoading = true;
  List<dynamic> _allVisits = [];
  List<dynamic> _filteredVisits = [];
  String? _error;
  String? _selectedStatusFilter; // <-- فقط عرف المتغير بدون = null
    // ignore: prefer_final_fields
  List<bool> _isSelected = [true, false, false]; // الكل, المكتملة, المتبقية
  final List<String?> _filterValues = [null, 'Completed', 'Pending'];
  int _totalCount = 0;
  int _completedCount = 0;
  int _pendingCount = 0;
  // --- نهاية متغيرات الحالة ---

  @override
  void initState() {
    super.initState();
    _fetchVisits();
  }

// --- دالة جلب البيانات (معدلة لاستخدام التوكن والتحقق منه + الاحتفاظ بمنطقك) ---
  Future<void> _fetchVisits() async {
    // تأكد من أن الويدجت لا يزال موجوداً
    if (!mounted) return;

    // إظهار مؤشر التحميل ومسح أي خطأ سابق
    setState(() {
      _isLoading = true;
      _error = null; // استخدام اسم متغير الخطأ لديك
    });

    // بناء الـ URL (استخدم متغير الفلتر الحالي لديك)
    final url = Uri.parse('http://10.0.2.2:5000/driver/${widget.driverId}/visits'); // URL الأساسي
    developer.log('Fetching visits from: $url');

    try {
        // +++ الخطوة 1: الحصول على الهيدرز بالتوكن +++
        // تأكد أنك أضفت import للملف المساعد أو الدالة معرفة هنا
        final headers = await getAuthenticatedHeaders(needsContentType: false);

        // +++ الخطوة 2: إرسال الطلب مع الهيدرز +++
        final response = await http.get(url, headers: headers).timeout(const Duration(seconds: 20));

        if (!mounted) return;

        // +++ الخطوة 3: التحقق من خطأ 401 أولاً +++
        if (response.statusCode == 401) {
            // تأكد أنك أضفت import للملف المساعد أو الدالة معرفة هنا
            await handleUnauthorized(context); // التعامل مع التوكن غير الصالح
            // لا داعي لـ setState هنا لأن handleUnauthorized سيقوم بالانتقال
            // لكن قد تحتاج لإيقاف التحميل إذا لم يتم الانتقال فوراً
            if (mounted) setState(() { _isLoading = false; });
            return; // الخروج مبكراً
        }
        // +++++++++++++++++++++++++++++++++++++++

        // --- إذا لم يكن 401، أكمل معالجة الرد ---
        if (response.statusCode == 200) {
            final List<dynamic> decodedData = jsonDecode(response.body);
            developer.log('All visits data received: ${decodedData.length} items');

            // --- الاحتفاظ بمنطق حساب الأعداد وتحديث الحالة لديك ---
            int pending = 0;
            int completed = 0;
            // استخدام النوع الصحيح للقائمة الكاملة
            final List<Map<String, dynamic>> allVisitsData = List<Map<String, dynamic>>.from(
              decodedData.whereType<Map<String, dynamic>>()
            );

            for (var visit in allVisitsData) {
                // لا حاجة للتحقق is Map هنا
                if (visit['visit_status'] == 'Completed') {
                  completed++;
                } else if (visit['visit_status'] == 'Pending') {
                  pending++;
                }
            }

            // تحديث الحالة بعد جلب البيانات بنجاح
            setState(() {
              _allVisits = allVisitsData; // استخدام متغير القائمة الكاملة لديك
              _totalCount = allVisitsData.length; // استخدام متغير العدد الكلي لديك
              _completedCount = completed; // استخدام متغير العدد المكتمل لديك
              _pendingCount = pending; // استخدام متغير العدد المعلق لديك
              _applyFilter(); // استخدام دالة الفلترة لديك (تأكد من وجودها)
              _isLoading = false; // إيقاف التحميل
              _error = null; // مسح الخطأ
            });
            // --- نهاية منطقك الحالي ---

        } else {
            // التعامل مع أخطاء السيرفر الأخرى
             developer.log('Failed to load visits. Status code: ${response.statusCode}');
             developer.log('Response body: ${response.body}');
             if (mounted) {
               setState(() {
                 _error = 'فشل تحميل الزيارات (رمز: ${response.statusCode})';
                 _isLoading = false;
                 // استخدام متغيراتك ودالتك الصحيحة للتصفير
                 _allVisits = [];
                 _filteredVisits = []; // افترض أن الفلتر يصفرها أيضاً
                 _resetCounts(); // تأكد من وجود هذه الدالة أو صفر المتغيرات يدوياً
               });
             }
        }
    } catch (error, s) { // التعامل مع أخطاء الاتصال أو المهلة أو فك التشفير
        developer.log('Error fetching visits: ${error.toString()}', error: error, stackTrace: s);
        if (!mounted) return;
        setState(() {
          _error = 'حدث خطأ في الاتصال: ${error.toString()}';
          _isLoading = false;
           // استخدام متغيراتك ودالتك الصحيحة للتصفير
           _allVisits = [];
           _filteredVisits = [];
           _resetCounts(); // تأكد من وجود هذه الدالة أو صفر المتغيرات يدوياً
        });
    }
    // لا حاجة لـ finally لإيقاف التحميل لأنه يتم في كل مسار
  }
  // --- نهاية الدالة المعدلة ---

  // --- دالة تطبيق الفلترة محلياً ---
  void _applyFilter() {
    if (_selectedStatusFilter == null) { // الكل
      _filteredVisits = List.from(_allVisits);
    } else { // Pending or Completed
      _filteredVisits = _allVisits.where((visit) {
        return visit is Map && visit['visit_status'] == _selectedStatusFilter;
      }).toList();
    }
    // لا نحتاج setState هنا لأنها تُستدعى من مكان آخر
  }

  // --- دالة تصفير العدادات ---
   void _resetCounts(){
      _totalCount = 0; _completedCount = 0; _pendingCount = 0;
   }


  @override
  Widget build(BuildContext context) {
    // +++ تغليف الشاشة بمتحكم التبويبات +++
    return DefaultTabController(
      length: 2, 
      child: Scaffold(
        appBar: AppBar(
          title: const Text('قائمة المحلات'),
          centerTitle: true,
          actions: [ IconButton(onPressed: _fetchVisits, icon: const Icon(Icons.refresh), tooltip: 'تحديث القائمة') ],
          // +++ شريط التبويبات الحديث +++
          bottom: const TabBar(
            labelColor: Color.fromARGB(255, 17, 5, 5),
            unselectedLabelColor: Color.fromARGB(179, 14, 7, 7),
            indicatorColor: Color.fromARGB(255, 73, 16, 16),
            indicatorWeight: 4,
            labelStyle: TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
            tabs: [
              Tab(icon: Icon(Icons.route), text: 'جولة اليوم 📍'),
              Tab(icon: Icon(Icons.warning_amber_rounded), text: 'طلبات عاجلة 🚨'),
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
                  for (int i = 0; i < _isSelected.length; i++) { _isSelected[i] = i == index; }
                  _selectedStatusFilter = _filterValues[index];
                  _applyFilter(); // تطبيق الفلتر محلياً
                });
              },
              borderRadius: BorderRadius.circular(8.0),
              constraints: BoxConstraints(minHeight: 40.0, minWidth: (MediaQuery.of(context).size.width - 32) / 3.1),
              children: <Widget>[
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Text('الكل ($_totalCount)')),
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Text('المكتملة ($_completedCount)')),
                Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Text('المتبقية ($_pendingCount)')),
              ],
            ),
          ),
          const Divider(height: 1, thickness: 1),

          // --- عرض المحتوى (القائمة أو الرسائل الأخرى) ---
          Expanded(
             child: _buildContent(),
          ),
        ],
      ),
      // +++ إضافة الزر العائم هنا +++
      floatingActionButton: FloatingActionButton(
        onPressed: () async { 
          // +++ التحقق من الضوء الأخضر قبل فتح صفحة الإضافة +++
          const storage = FlutterSecureStorage();
          String? authStr = await storage.read(key: 'is_authorized');
          
          // الحماية السحرية الأولى: التأكد أن الشاشة ما زالت موجودة بعد القراءة
          if (!context.mounted) return; 

          if (authStr != 'true') {
             ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
               content: Text('غير مصرح لك بإضافة محلات حالياً. بانتظار تفعيل خط السير من الإدارة.'),
               backgroundColor: Colors.orange,
             ));
             return; // إيقاف العملية فوراً ومنع فتح الشاشة
          }
          // ++++++++++++++++++++++++++++++++++++++++++++++

          // --- الكود الأصلي لفتح شاشة إضافة المحل ---
          final result = await Navigator.push<bool>( 
            context,
            MaterialPageRoute(builder: (context) => const AddShopScreen()),
          );
          
          // الحماية السحرية الثانية: التأكد أن الشاشة موجودة بعد العودة من الإضافة
          if (!context.mounted) return; 
          
          if (result == true) {
             developer.log('AddShopScreen closed with success, refreshing visits...');
            _fetchVisits(); 
          }
        },

        tooltip: 'إضافة محل جديد', 
        child: const Icon(Icons.add), 
      ),
    ), // +++ إغلاق Scaffold +++
    ); // +++ إغلاق DefaultTabController +++
  }


  Widget _buildContent() {
    // الأولوية لعرض الخطأ إن وجد
    if (_error != null) {
       return Center(
         child: Padding(
           padding: const EdgeInsets.all(16.0),
           child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
               Text('حدث خطأ: $_error', style: const TextStyle(color: Colors.red)),
               const SizedBox(height: 10),
               ElevatedButton(onPressed: _fetchVisits, child: const Text('إعادة المحاولة'))
           ]),
         ),
       );
    }
    // ثم عرض مؤشر التحميل
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    // +++ فصل الزيارات بعد فلترتها (حفاظاً على منطقك الأصلي) +++
    final List<dynamic> normalVisits = _filteredVisits.where((v) => v['is_emergency'] != true).toList();
    final List<dynamic> emergencyVisits = _filteredVisits.where((v) => v['is_emergency'] == true).toList();

    // +++ عرض التبويبات +++
    return TabBarView(
      children: [
        _buildListView(normalVisits, isEmergencyTab: false),
        _buildListView(emergencyVisits, isEmergencyTab: true),
      ],
    );
  }

  // --- دالة مساعدة لبناء القائمة بتصميم "البطاقات" الحديث ---
  Widget _buildListView(List<dynamic> visitsList, {required bool isEmergencyTab}) {
    if (visitsList.isEmpty) {
      String emptyMessage = isEmergencyTab ? 'لا يوجد طلبات طارئة حالياً 🚨' : 'لا توجد زيارات مجدولة لك حالياً 📍';
      if (_selectedStatusFilter == 'Pending') {
        emptyMessage = isEmergencyTab ? 'لا يوجد طلبات طارئة متبقية.' : 'لا توجد زيارات متبقية.';
      } else if (_selectedStatusFilter == 'Completed') {
        emptyMessage = isEmergencyTab ? 'لم تقم بإكمال أي طلب طارئ بعد.' : 'لم تقم بإكمال أي زيارة بعد.';
      }
      return RefreshIndicator(
        onRefresh: _fetchVisits, 
        child: ListView(children: [Padding(padding: const EdgeInsets.only(top: 50.0), child: Center(child: Text(emptyMessage, style: const TextStyle(fontSize: 16, color: Colors.grey, fontWeight: FontWeight.bold))))])
      );
    }

    return RefreshIndicator(
      onRefresh: _fetchVisits,
      child: ListView.builder(
        key: PageStorageKey<String>('visitListScroll_${isEmergencyTab ? "emg" : "norm"}'),
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
          
          final shopBalance = (visit['shop_balance'] ?? 0.0).toDouble();
          final bool hasNotes = visit['visit_notes'] != null && visit['visit_notes'].toString().isNotEmpty;
          final int? sequence = visit['visit_sequence'];
          final String sequenceDisplay = sequence?.toString() ?? '-';

          bool isCompleted = visitStatus == 'Completed';
          bool isAttempted = visitStatus == 'Pending' && hasNotes;

          // --- تصميم الألوان والأيقونات الذكي ---
          IconData leadingIcon = isEmergencyTab ? Icons.warning_amber_rounded : Icons.storefront;
          Color iconColor = Colors.blueGrey;
          Color cardBorderColor = Colors.grey.shade300;
          Color cardBgColor = isEmergencyTab ? Colors.red.shade50.withValues(alpha: 0.3) : Colors.white;

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
                 // --- تم الاحتفاظ بالكود الأصلي للانتقال 100% لضمان عدم حدوث أي خلل ---
                 final int visitId = visit['visit_id'] ?? 0;
                 final String currentStatus = visitStatus;
                 final double currentBalance = shopBalance; 

                 developer.log('Navigating to VisitScreen for visit ID: $visitId');

                 final result = await Navigator.push(
                   context,
                   MaterialPageRoute(
                     builder: (context) => VisitScreen(
                       visitId: visitId,
                       shopName: shopName,
                       shopBalance: currentBalance, 
                       visitStatus: currentStatus,
                     ),
                   ),
                 );

                 if (result == true && mounted) {
                    developer.log('Returned from VisitScreen with success, performing full refresh...');
                    _fetchVisits(); 
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
                        color: isCompleted ? Colors.green.shade100 : (isEmergencyTab ? Colors.red.shade100 : Colors.blue.shade50),
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
                          Text('$sequenceDisplay. $shopName', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                          const SizedBox(height: 6),
                          Row(
                            children: [
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                decoration: BoxDecoration(
                                  color: isCompleted ? Colors.green : (isAttempted ? Colors.orange : Colors.blueGrey), 
                                  borderRadius: BorderRadius.circular(8)
                                ),
                                child: Text(statusInArabic, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold)),
                              ),
                              const SizedBox(width: 10),
                              Text('الذمة: ${shopBalance.toStringAsFixed(2)} د.أ', style: TextStyle(color: Colors.grey.shade700, fontSize: 13, fontWeight: FontWeight.w600)),
                            ],
                          )
                        ],
                      ),
                    ),
                    
                    Icon(Icons.arrow_forward_ios, size: 16, color: Colors.grey.shade400),
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