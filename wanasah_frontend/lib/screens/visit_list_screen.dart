import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:developer' as developer;
import 'visit_screen.dart'; // نحتاج هذا للانتقال
import '../services/auth_utils.dart';
import 'package:wanasah_frontend/screens/add_shop_screen.dart';
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
    return Scaffold(
      appBar: AppBar(
        title: const Text('قائمة المحلات'), // <-- النص المطلوب فقط
        centerTitle: true,
        actions: [ IconButton(onPressed: _fetchVisits, icon: const Icon(Icons.refresh), tooltip: 'تحديث القائمة') ],
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
        onPressed: () async { // <-- لاحظ إضافة كلمة async هنا
  // الكود الذي ينتقل لشاشة إضافة المحل
  // تأكد من استيراد AddShopScreen في الأعلى
  final result = await Navigator.push<bool>( // نستخدم await ونحدد النوع <bool>
    context,
    MaterialPageRoute(builder: (context) => const AddShopScreen()),
  );

  // التحقق من النتيجة بعد العودة من AddShopScreen
  // تأكد من أن الويدجت لا يزال موجوداً قبل استدعاء fetchVisits
  if (mounted && result == true) {
     developer.log('AddShopScreen closed with success, refreshing visits...'); // يمكنك إضافة هذا للتحقق
    _fetchVisits(); // استدعاء الدالة التي تجلب الزيارات
  }
},
        tooltip: 'إضافة محل جديد', // يظهر عند الضغط المطول
        child: const Icon(Icons.add), // أيقونة علامة زائد
        // يمكنك تغيير لونه أو شكله باستخدام backgroundColor أو shape
        // backgroundColor: Theme.of(context).primaryColor,
      ),
      // ++++++++++++++++++++++++++++++
    );
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
    // ثم عرض مؤشر التحميل إذا كانت البيانات لا تزال تُجلب لأول مرة
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    // ثم عرض رسالة القائمة الفارغة (بناءً على الفلتر المختار)
    if (_filteredVisits.isEmpty) {
      String emptyMessage = 'لا توجد زيارات لعرضها بهذا الفلتر.';
       if (_selectedStatusFilter == 'Pending') {
  emptyMessage = 'لا توجد زيارات متبقية.';
       }
       else if (_selectedStatusFilter == 'Completed') {
  emptyMessage = 'لم تقم بإكمال أي زيارات بعد.';
}
       else if (_selectedStatusFilter == null && _allVisits.isEmpty) {
  emptyMessage = 'لا توجد زيارات مجدولة لك حالياً.';
}
        return RefreshIndicator(onRefresh: _fetchVisits, child: ListView(children: [Padding(padding: const EdgeInsets.only(top: 50.0), child: Center(child: Text(emptyMessage)))]));
    }
    // أخيراً، عرض القائمة المفلتَرة
    return RefreshIndicator(
        onRefresh: _fetchVisits, // السحب للأسفل يجلب كل البيانات من جديد
        child: ListView.builder(
          key: PageStorageKey<String>('visitListScroll'),
          itemCount: _filteredVisits.length,
          itemBuilder: (context, index) {
          final visit = _filteredVisits[index] as Map<String, dynamic>;
          final shopName = visit['shop_name'] ?? 'اسم المحل غير متوفر';
          final visitStatus = visit['visit_status'] ?? 'غير محدد';
          // كود تحويل الحالة للعربية
    String statusInArabic;
    if (visitStatus == 'Completed') {
      statusInArabic = 'مكتملة';
    } else if (visitStatus == 'Pending') {
      statusInArabic = 'قيد الانتظار';
      // يمكنك إضافة حالات أخرى هنا مثل 'Attempted' -> 'تمت المحاولة'
    } else {
      statusInArabic = visitStatus; // عرض القيمة كما هي للحالات غير المتوقعة
    }
          final shopBalance = (visit['shop_balance'] ?? 0.0).toDouble();
          final bool hasNotes = visit['visit_notes'] != null && visit['visit_notes'].toString().isNotEmpty;

          // <<<--- الخطوة 3: استخراج رقم التسلسل المستلم من الـ API --->>>
          final int? sequence = visit['visit_sequence']; // قد يكون null
          // تحويل الرقم إلى نص للعرض، أو عرض "-" إذا كان null
          final String sequenceDisplay = sequence?.toString() ?? '-';

          // ... (كود تحديد الأيقونة واللون يبقى كما هو) ...
          IconData leadingIcon = Icons.storefront; // القيمة الافتراضية (Pending بدون ملاحظات)
          Color iconColor = Colors.blueGrey;    // القيمة الافتراضية
          // ... (if/else if/else لتحديد الأيقونة واللون) ...
          // الأسطر التالية لتحديد إذا كانت مكتملة أو محاولة
      bool isCompleted = visitStatus == 'Completed';
      bool isAttempted = visitStatus == 'Pending' && hasNotes; // نفترض hasNotes معرفة قبلها

      // تغيير القيم فقط للحالات الخاصة
      if (isCompleted) {
        leadingIcon = Icons.check_circle;
        iconColor = Colors.green;
      } else if (isAttempted) {
        leadingIcon = Icons.history;
        iconColor = Colors.orange;
      }
      // لا نحتاج else هنا


          return ListTile(
            leading: Icon(leadingIcon, color: iconColor),

            // <<<--- الخطوة 4: تم تعديل title هنا لعرض الرقم التسلسلي المستلم --->>>
            title: Text('$sequenceDisplay. $shopName'), // عرض الرقم ثم نقطة ثم مسافة ثم الاسم

            subtitle: Text('الحالة: $statusInArabic - الذمة: $shopBalance'), // <-- استخدم statusInArabic هنا
            onTap: () async {
                 final int visitId = visit['visit_id'] ?? 0;
                 final String currentStatus = visitStatus;
                 final double currentBalance = shopBalance; // تمرير الرصيد الحالي

                 developer.log('Navigating to VisitScreen for visit ID: $visitId');

                 // الانتقال وانتظار النتيجة
                 final result = await Navigator.push(
                   context,
                   MaterialPageRoute(
                     builder: (context) => VisitScreen(
                       visitId: visitId,
                       shopName: shopName,
                       shopBalance: currentBalance, // استخدام الرصيد الحالي
                       visitStatus: currentStatus,
                     ),
                   ),
                 );

                 // ---<<< التحقق من النتيجة وإعادة تحميل الكل لضمان الدقة >>>---
                 // هذا أبسط ويضمن تحديث الحالة والأعداد بشكل صحيح دائماً
                 // لكنه قد يعيد المستخدم لأعلى القائمة
                 if (result == true && mounted) {
                    developer.log('Returned from VisitScreen with success, performing full refresh...');
                    _fetchVisits(); // <<<--- استدعاء fetchVisits لتحديث كل شيء
                 }
                 // ---<<< نهاية التحقق وإعادة التحميل >>>---

              }, // نهاية onTap
            ); // نهاية ListTile
          },
        ),
      );
    }
  }

 // نهاية كلاس _HomeScreenState