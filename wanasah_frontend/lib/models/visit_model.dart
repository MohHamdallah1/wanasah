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
    final isEmergRaw = json['is_emergency'];
    final bool parsedEmergency = isEmergRaw == true || isEmergRaw == 1 || isEmergRaw == 'true' || isEmergRaw == '1';

    // +++ استخراج بيانات المحل المتداخلة من الباك-إند (الدرع الفولاذي) +++
    final Map<String, dynamic> shopData = (json['shop'] as Map<String, dynamic>?) ?? {};

    return VisitModel(
      id: int.tryParse((json['id'] ?? json['visit_id'])?.toString() ?? '0') ?? 0,
      shopId: int.tryParse((json['shop_id'] ?? shopData['id'])?.toString() ?? '0') ?? 0,
      
      // +++ البحث في المستوى المسطح ثم المتداخل +++
      shopName: json['shop_name']?.toString() ?? json['shopName']?.toString() ?? shopData['name']?.toString() ?? 'محل غير معروف',

      shopBalance: double.tryParse(
            json['shop_balance']?.toString() ??
            json['current_balance']?.toString() ??
            shopData['current_balance']?.toString() ?? '0') ?? 0.0,
          
      maxDebtLimit: double.tryParse(
            json['max_debt_limit']?.toString() ?? 
            shopData['max_debt_limit']?.toString() ?? '0') ?? 0.0,

      shopZoneId: int.tryParse((json['shop_zone_id'] ?? shopData['zone_id'])?.toString() ?? ''),
      allowedZoneId: int.tryParse(json['allowed_zone_id']?.toString() ?? ''),
      
      status: json['status']?.toString() ?? json['visit_status']?.toString() ?? 'Pending',
      outcome: json['outcome']?.toString() ?? '', 
      
      sequence: int.tryParse(json['sequence']?.toString() ?? json['visit_sequence']?.toString() ?? shopData['sequence']?.toString() ?? '999') ?? 999,
      
      shopOwner: json['shop_owner']?.toString() ?? shopData['contact_person']?.toString(),
      shopPhone: json['shop_phone']?.toString() ?? shopData['phone_number']?.toString(),
      isEmergency: parsedEmergency,
      locationLink: json['location_link']?.toString() ?? json['shop_location_link']?.toString() ?? shopData['location_link']?.toString(),

      latitude: double.tryParse((json['latitude'] ?? json['shop_latitude'] ?? shopData['latitude'])?.toString() ?? ''),
      longitude: double.tryParse((json['longitude'] ?? json['shop_longitude'] ?? shopData['longitude'])?.toString() ?? ''),
      
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
