// File: lib/models/visit_model.dart

class VisitModel {
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

  VisitModel({
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
      id: json['id'] ?? json['visit_id'] ?? 0,
      shopId: json['shop_id'] ?? 0,
      shopName: json['shop_name'] ?? json['shopName'] ?? 'محل غير معروف',
      shopBalance:
          (json['shop_balance'] ?? json['current_balance'] ?? 0).toDouble(),
      maxDebtLimit: (json['max_debt_limit'] ?? 0).toDouble(),
      shopZoneId: json['shop_zone_id'], // +++
      allowedZoneId: json['allowed_zone_id'], // +++
      // توحيد الحالات حسب ما يرسله الباك-إند بالضبط (يدعم مسار القائمة ومسار التفاصيل)
      status: json['status'] ?? json['visit_status'] ?? 'Pending',
      outcome:
          json['outcome'] ??
          '', // إزالة 'None' وجعلها فارغة لتطابق الباك-إند وتمنع مشاكل الواجهة
      // +++ تعبئة الحقول الجديدة +++
      sequence: json['sequence'] ?? json['visit_sequence'] ?? 999,
      isEmergency: parsedEmergency,
      locationLink: json['location_link'] ?? json['shop_location_link'],

      // معالجة الخرائط وتجنب أخطاء التحويل من Integer إلى Double
      latitude:
          json['latitude'] != null || json['shop_latitude'] != null
              ? (json['latitude'] ?? json['shop_latitude']).toDouble()
              : null,
      longitude:
          json['longitude'] != null || json['shop_longitude'] != null
              ? (json['longitude'] ?? json['shop_longitude']).toDouble()
              : null,
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
    };
  }
}
