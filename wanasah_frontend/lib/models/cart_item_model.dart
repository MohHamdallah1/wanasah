// File: lib/models/cart_item_model.dart

class CartItemModel {
  final int productVariantId;
  final String name;
  final double pricePerCarton;
  final double pricePerPack;
  final int packsPerCarton;

  // المخزون المتاح في السيارة للمراقبة
  final int availableCartons;
  final int availablePacks;

  // المبيعات
  final int cartons;
  final int packs;

  // المرتجعات والتوالف
  final int returnCartons;
  final int returnPacks;
  final String returnReason;

  // العينات
  final int sampleCartons;
  final int samplePacks;

  CartItemModel({
    required this.productVariantId,
    required this.name,
    required this.pricePerCarton,
    required this.pricePerPack,
    required this.packsPerCarton,
    required this.availableCartons,
    required this.availablePacks,
    this.cartons = 0,
    this.packs = 0,
    this.returnCartons = 0,
    this.returnPacks = 0,
    this.returnReason = '',
    this.sampleCartons = 0,
    this.samplePacks = 0,
  });

  // --- دوال الحساب الذكية الداخلية ---

  // حساب قيمة المبيعات للصنف
  double get totalSalePrice =>
      (cartons * pricePerCarton) + (packs * pricePerPack);

  // حساب قيمة المرتجعات للصنف
  double get totalReturnPrice =>
      (returnCartons * pricePerCarton) + (returnPacks * pricePerPack);

  // إجمالي الحبات المباعة (للتأكد من المخزون)
  int get totalSoldPacks => (cartons * packsPerCarton) + packs;

  // إجمالي الحبات المتاحة بالسيارة
  int get totalAvailablePacks =>
      (availableCartons * packsPerCarton) + availablePacks;

  // التحقق من صحة المخزون
  bool get hasEnoughInventory => totalSoldPacks <= totalAvailablePacks;

  // دالة النسخ للتعديل الآمن في الـ BLoC
  CartItemModel copyWith({
    int? cartons,
    int? packs,
    int? returnCartons,
    int? returnPacks,
    String? returnReason,
    int? sampleCartons,
    int? samplePacks,
  }) {
    return CartItemModel(
      productVariantId: productVariantId,
      name: name,
      pricePerCarton: pricePerCarton,
      pricePerPack: pricePerPack,
      packsPerCarton: packsPerCarton,
      availableCartons: availableCartons,
      availablePacks: availablePacks,
      cartons: cartons ?? this.cartons,
      packs: packs ?? this.packs,
      returnCartons: returnCartons ?? this.returnCartons,
      returnPacks: returnPacks ?? this.returnPacks,
      returnReason: returnReason ?? this.returnReason,
      sampleCartons: sampleCartons ?? this.sampleCartons,
      samplePacks: samplePacks ?? this.samplePacks,
    );
  }
}
