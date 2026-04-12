// File: lib/models/product_model.dart

class ProductModel {
  final int id;
  final String name;
  final double pricePerCarton;
  final double pricePerPack;
  final int packsPerCarton;
  final int
  startingCartons; // +++ الحقل الجديد لحفظ كمية الاستلام (بضاعة أول المدة) +++
  final int currentCartons;
  final int currentPacks;

  ProductModel({
    required this.id,
    required this.name,
    required this.pricePerCarton,
    required this.pricePerPack,
    required this.packsPerCarton,
    this.startingCartons = 0, // القيمة الافتراضية
    this.currentCartons = 0,
    this.currentPacks = 0,
  });

  factory ProductModel.fromJson(Map<String, dynamic> json) {
    return ProductModel(
      id: json['id'] ?? json['product_variant_id'] ?? 0,
      name:
          json['name'] ??
          json['product_name'] ??
          json['variant_name'] ??
          'منتج غير معروف',
      pricePerCarton: (json['price_per_carton'] ?? 0).toDouble(),
      pricePerPack: (json['price_per_pack'] ?? 0).toDouble(),
      packsPerCarton: json['packs_per_carton'] ?? 1,
      // +++ قراءة الاستلام من السيرفر أو من SQLite +++
      startingCartons: json['starting_cartons'] ?? 0,
      currentCartons: json['current_cartons'] ?? json['remaining_cartons'] ?? 0,
      currentPacks: json['current_packs'] ?? json['remaining_packs'] ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'price_per_carton': pricePerCarton,
      'price_per_pack': pricePerPack,
      'packs_per_carton': packsPerCarton,
      'starting_cartons': startingCartons, // +++ حفظ الاستلام محلياً +++
      'current_cartons': currentCartons,
      'current_packs': currentPacks,
    };
  }
}
