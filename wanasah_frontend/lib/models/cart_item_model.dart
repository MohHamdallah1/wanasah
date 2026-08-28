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

  // المبيعات (تخصم من المخزون، وتزيد الفلوس)
  final int cartons;
  final int packs;

  // +++ النسف المعماري: عدادات استبدال التوالف المباشرة (1:1) +++
  final int returnFactoryCartons;
  final int returnFactoryPacks;
  final int returnExpiredCartons;
  final int returnExpiredPacks;

  // العينات (تخصم من المخزون مجاناً)
  final int sampleCartons;
  final int samplePacks;
  final String sampleReason; 

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
    this.returnFactoryCartons = 0,
    this.returnFactoryPacks = 0,
    this.returnExpiredCartons = 0,
    this.returnExpiredPacks = 0,
    this.sampleCartons = 0,
    this.samplePacks = 0,
    this.sampleReason = '',
  });

  // --- دوال الحساب الذكية الداخلية ---

  // حساب قيمة المبيعات للصنف
  double get totalSalePrice =>
      (cartons * pricePerCarton) + (packs * pricePerPack);

  // +++ الدرع المحاسبي: الاستبدال صفر فلوس +++
  double get totalReturnPrice => 0.0;

  // إجمالي الحبات المباعة 
  int get totalSoldPacks => (cartons * packsPerCarton) + packs;

  // +++ الكيّ الجراحي (حساب المخزون الشامل): البضاعة المخصومة = المبيعات + العينات + (الاستبدال) +++
  // لأن كل كرتونة تالفة استلمناها، سحبنا مكانها كرتونة صالحة من السيارة!
  int get totalDeductedPacks =>
      totalSoldPacks + 
      (sampleCartons * packsPerCarton) + samplePacks +
      (returnFactoryCartons * packsPerCarton) + returnFactoryPacks +
      (returnExpiredCartons * packsPerCarton) + returnExpiredPacks;

  // إجمالي الحبات المتاحة بالسيارة
  int get totalAvailablePacks =>
      (availableCartons * packsPerCarton) + availablePacks;

  // التحقق من صحة المخزون
  bool get hasEnoughInventory => totalDeductedPacks <= totalAvailablePacks;

  // +++ محول الـ API الخفي (Adapter Pattern): لتتوافق العدادات مع الباك إند دون كسر الـ API +++
  List<Map<String, dynamic>> get returns {
    final List<Map<String, dynamic>> list = [];
    if (returnFactoryCartons > 0 || returnFactoryPacks > 0) {
      list.add({'type': 'Factory_Defect', 'cartons': returnFactoryCartons, 'packs': returnFactoryPacks});
    }
    if (returnExpiredCartons > 0 || returnExpiredPacks > 0) {
      list.add({'type': 'Expired', 'cartons': returnExpiredCartons, 'packs': returnExpiredPacks});
    }
    return list;
  }

  // دالة النسخ للتعديل الآمن في الـ BLoC
  CartItemModel copyWith({
    int? availableCartons, // +++ الكي الجراحي: السماح بتحديث المخزون +++
    int? availablePacks,   // +++ الكي الجراحي: السماح بتحديث المخزون +++
    int? cartons,
    int? packs,
    int? returnFactoryCartons,
    int? returnFactoryPacks,
    int? returnExpiredCartons,
    int? returnExpiredPacks,
    int? sampleCartons,
    int? samplePacks,
    String? sampleReason,
  }) {
    return CartItemModel(
      productVariantId: productVariantId,
      name: name,
      pricePerCarton: pricePerCarton,
      pricePerPack: pricePerPack,
      packsPerCarton: packsPerCarton,
      availableCartons: availableCartons ?? this.availableCartons, // +++ ربط التحديث +++
      availablePacks: availablePacks ?? this.availablePacks,       // +++ ربط التحديث +++
      cartons: cartons ?? this.cartons,
      packs: packs ?? this.packs,
      returnFactoryCartons: returnFactoryCartons ?? this.returnFactoryCartons,
      returnFactoryPacks: returnFactoryPacks ?? this.returnFactoryPacks,
      returnExpiredCartons: returnExpiredCartons ?? this.returnExpiredCartons,
      returnExpiredPacks: returnExpiredPacks ?? this.returnExpiredPacks,
      sampleCartons: sampleCartons ?? this.sampleCartons,
      samplePacks: samplePacks ?? this.samplePacks,
      sampleReason: sampleReason ?? this.sampleReason,
    );
  }
}