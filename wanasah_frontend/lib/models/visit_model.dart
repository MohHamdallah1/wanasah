// File: lib/models/visit_model.dart

class VisitModel {
  final int id;
  final int shopId;
  final String shopName;
  final double shopBalance;
  final String status;
  final String outcome;

  VisitModel({
    required this.id,
    required this.shopId,
    required this.shopName,
    required this.shopBalance,
    required this.status,
    required this.outcome,
  });

  factory VisitModel.fromJson(Map<String, dynamic> json) {
    return VisitModel(
      id: json['id'] ?? 0,
      shopId: json['shop_id'] ?? 0,
      shopName: json['shop_name'] ?? json['shopName'] ?? 'محل غير معروف',
      // معالجة الأرقام لتجنب أخطاء (int vs double)
      shopBalance:
          (json['shop_balance'] ?? json['current_balance'] ?? 0).toDouble(),
      status: json['status'] ?? 'Pending',
      outcome: json['outcome'] ?? 'None',
    );
  }
}
