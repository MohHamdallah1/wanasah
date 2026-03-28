// File: lib/models/product_model.dart

class ProductModel {
  final int id;
  final String name;
  final double pricePerCarton;
  final double pricePerPack;
  final int packsPerCarton;
  final int currentCartons;
  final int currentPacks;

  ProductModel({
    required this.id,
    required this.name,
    required this.pricePerCarton,
    required this.pricePerPack,
    required this.packsPerCarton,
    this.currentCartons = 0,
    this.currentPacks = 0,
  });

  // دالة تحويل البيانات القادمة من السيرفر (JSON) إلى كائن آمن
  factory ProductModel.fromJson(Map<String, dynamic> json) {
    return ProductModel(
      id: json['id'] ?? json['product_variant_id'] ?? 0,
      name:
          json['name'] ??
          json['productName'] ??
          json['variant_name'] ??
          'منتج غير معروف',
      pricePerCarton: (json['price_per_carton'] ?? 0).toDouble(),
      pricePerPack: (json['price_per_pack'] ?? 0).toDouble(),
      packsPerCarton: json['packs_per_carton'] ?? 1,
      currentCartons: json['current_cartons'] ?? json['remaining_cartons'] ?? 0,
      currentPacks: json['current_packs'] ?? json['remaining_packs'] ?? 0,
    );
  }

  // دالة لتحويل الكائن إلى JSON لإرساله للسيرفر
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'price_per_carton': pricePerCarton,
      'price_per_pack': pricePerPack,
      'packs_per_carton': packsPerCarton,
    };
  }
}
