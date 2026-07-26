// File: lib/models/visit_model.dart
import 'dart:convert';
import 'package:equatable/equatable.dart';
// +++ النسف المعماري للأداء (Equatable Enforcement): جعل الموديل قابلاً للمقارنة الذكية لمنع وميض الواجهة +++
class VisitModel extends Equatable {
  final int id;
  final int shopId;
  final String shopName;
  final double shopBalance;
  final double maxDebtLimit; // +++ استقبال السقف +++
  final int? shopZoneId; // +++
  final int? allowedZoneId; // +++
  final String status;
  final String outcome;

  // +++ الحقول الجديدة التي كانت مفقودة وتسببت بالانهيار المعماري +++
  final int sequence;
  final bool isEmergency;
  final String? locationLink;
  final double? latitude;
  final double? longitude;
  // +++ الدرع الميداني: استقبال معلومات الاتصال +++
  final String? shopOwner;
  final String? shopPhone;
  final String? cartItemsJson; // +++ لحفظ السلة محلياً (تم تحويلها لـ final لضمان الثبات) +++
  final String? returnsJson; // +++ لحفظ التوالف محلياً +++

  const VisitModel({
    required this.id,
    required this.shopId,
    required this.shopName,
    required this.shopBalance,
    required this.maxDebtLimit,
    this.shopZoneId,
    this.allowedZoneId,
    required this.status,
    required this.outcome,
    required this.sequence,
    required this.isEmergency,
    this.locationLink,
    this.latitude,
    this.longitude,
    this.shopOwner, // +++
    this.shopPhone, // +++
    this.cartItemsJson, 
    this.returnsJson,
  });

  // دالة تحويل البيانات القادمة من السيرفر (أو SQLite) إلى كائن آمن
  factory VisitModel.fromJson(Map<String, dynamic> json) {
    // معالجة ذكية ومضادة للأخطاء لحالة الطوارئ (لأن SQLite يخزنها 1/0 والسيرفر يرسلها true/false/text)
    final isEmergRaw = json['is_emergency'];
    final bool parsedEmergency =
        isEmergRaw == true ||
        isEmergRaw == 1 ||
        isEmergRaw == 'true' ||
        isEmergRaw == '1';

    return VisitModel(
      // +++ الدرع النخبوي (Elite Safe Cast): تحويل أي رقم قادم كنص إلى int بأمان مطلق +++
      id: int.tryParse((json['id'] ?? json['visit_id'])?.toString() ?? '0') ?? 0,
      shopId: int.tryParse(json['shop_id']?.toString() ?? '0') ?? 0,
      shopName: json['shop_name']?.toString() ?? json['shopName']?.toString() ?? 'محل غير معروف',

      // +++ النسف المعماري: قراءة الحقل كنص ثم تحويله بأمان لمنع الـ Crash في حالة Float/String +++
      shopBalance:
          double.tryParse(
            json['shop_balance']?.toString() ??
                json['current_balance']?.toString() ??
                '0',
          ) ??
          0.0,
      maxDebtLimit:
          double.tryParse(json['max_debt_limit']?.toString() ?? '0') ?? 0.0,

      // +++ الحماية من فخ الـ SQLite (Int Cast Crash) +++
      shopZoneId: int.tryParse(json['shop_zone_id']?.toString() ?? ''),
      allowedZoneId: int.tryParse(json['allowed_zone_id']?.toString() ?? ''),
      
      // توحيد الحالات حسب ما يرسله الباك-إند بالضبط (يدعم مسار القائمة ومسار التفاصيل)
      status: json['status']?.toString() ?? json['visit_status']?.toString() ?? 'Pending',
      outcome: json['outcome']?.toString() ?? '', 
      
      // +++ تعبئة الحقول الجديدة (مع حماية التحويل من String إلى Integer) +++
      sequence:
          int.tryParse(
            json['sequence']?.toString() ??
                json['visit_sequence']?.toString() ??
                '999',
          ) ??
          999,
      // +++ قراءة معلومات الاتصال من الـ JSON +++
      shopOwner: json['shop_owner']?.toString(),
      shopPhone: json['shop_phone']?.toString(),
      isEmergency: parsedEmergency,
      locationLink: json['location_link']?.toString() ?? json['shop_location_link']?.toString(),

      // +++ النسف المعماري لقنبلة الـ toDouble() الموقوتة: الاعتماد على tryParse لابتلاع أي نوع بيانات +++
      latitude: double.tryParse((json['latitude'] ?? json['shop_latitude'])?.toString() ?? ''),
      longitude: double.tryParse((json['longitude'] ?? json['shop_longitude'])?.toString() ?? ''),
      // +++ الدرع الذاتي: إذا كانت القائمة تأتي من السيرفر (List) يتم تشفيرها، وإذا تأتي من SQLite (String) تبقى كما هي +++
      cartItemsJson: json['cart_items'] is String ? json['cart_items'] as String : (json['cart_items'] != null ? jsonEncode(json['cart_items']) : null),
      returnsJson: json['returns'] is String ? json['returns'] as String : (json['returns'] != null ? jsonEncode(json['returns']) : null),
    );
  }

  // +++ دالة جديدة لتسهيل حفظ الكائن لاحقاً في قاعدة البيانات المحلية (SQLite) +++
  Map<String, dynamic> toJson() {
    return {
      'visit_id': id,
      'shop_id': shopId,
      'shop_name': shopName,
      'shop_balance': shopBalance,
      'max_debt_limit': maxDebtLimit,
      'shop_zone_id': shopZoneId,
      'allowed_zone_id': allowedZoneId,
      'status': status,
      'outcome': outcome,
      'visit_sequence': sequence,
      'is_emergency': isEmergency ? 1 : 0,
      'location_link': locationLink,
      'latitude': latitude,
      'longitude': longitude,
      // +++ الدرع الميداني: حفظ بيانات الاتصال محلياً +++
      'shop_owner': shopOwner,
      'shop_phone': shopPhone,
      'cart_items': cartItemsJson,
      'returns': returnsJson,
    };
        }

  // +++ إخبار الـ BLoC بكيفية المقارنة لمنع إعادة البناء العبثي للواجهة +++
  @override
  List<Object?> get props => [
        id, shopId, shopName, shopBalance, maxDebtLimit, shopZoneId,
        allowedZoneId, status, outcome, sequence, isEmergency,
        locationLink, latitude, longitude, shopOwner, shopPhone,
        cartItemsJson, returnsJson,
      ];
  
}
