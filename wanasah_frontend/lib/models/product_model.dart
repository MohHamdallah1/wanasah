// File: lib/models/product_model.dart
import 'package:equatable/equatable.dart';
// +++  للأداء (Equatable Enforcement): جعل الموديل قابلاً للمقارنة الذكية +++
class ProductModel extends Equatable {
  final int id;
  final String name;
  final double pricePerCarton;
  final double pricePerPack;
  final int packsPerCarton;
  final int startingCartons; 
  final int startingPacks; // +++ استلام الكسور (الحبات) +++
  final int soldCartons;   // +++ المباع الصافي من السيرفر (كراتين) +++
  final int soldPacks;     // +++ المباع الصافي من السيرفر (حبات) +++
  final int currentCartons;
  final int currentPacks;

  const ProductModel({
    required this.id,
    required this.name,
    required this.pricePerCarton,
    required this.pricePerPack,
    required this.packsPerCarton,
    this.startingCartons = 0,
    this.startingPacks = 0,
    this.soldCartons = 0,
    this.soldPacks = 0,
    this.currentCartons = 0,
    this.currentPacks = 0,
  });

  factory ProductModel.fromJson(Map<String, dynamic> json) {
    // +++ الإعدام الفوري: منع تصادم المنتجات المجهولة في قاعدة البيانات (ID = 0) +++
    final parsedId = int.tryParse((json['id'] ?? json['product_variant_id'])?.toString() ?? '');
    if (parsedId == null || parsedId == 0) {
      throw FormatException('Critical Data Error: Invalid or missing product ID in payload');
    }

    // +++ حماية فولاذية من ثغرة القسمة على صفر (حتى لو أرسل السيرفر 0 صراحةً) +++
    final int rawPacks = int.tryParse(json['packs_per_carton']?.toString() ?? '1') ?? 1;
    final int safePacksPerCarton = rawPacks > 0 ? rawPacks : 1;

    return ProductModel(
      id: parsedId,
      name:
          json['name']?.toString() ??
          json['product_name']?.toString() ??
          json['variant_name']?.toString() ??
          'منتج غير معروف',
      
      pricePerCarton: double.tryParse(json['price_per_carton']?.toString() ?? '0') ?? 0.0,
      pricePerPack: double.tryParse(json['price_per_pack']?.toString() ?? '0') ?? 0.0,
      
      packsPerCarton: safePacksPerCarton,
      
      // +++ قراءة الاستلام والمباع من السيرفر أو من SQLite بأمان مطلق +++
      startingCartons: int.tryParse(json['starting_cartons']?.toString() ?? '0') ?? 0,
      startingPacks: int.tryParse(json['starting_packs']?.toString() ?? '0') ?? 0,
      soldCartons: int.tryParse(json['sold_cartons']?.toString() ?? '0') ?? 0,
      soldPacks: int.tryParse(json['sold_packs']?.toString() ?? '0') ?? 0,
      currentCartons: int.tryParse((json['current_cartons'] ?? json['remaining_cartons'])?.toString() ?? '0') ?? 0,
      currentPacks: int.tryParse((json['current_packs'] ?? json['remaining_packs'])?.toString() ?? '0') ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      // +++ إخراس البوت: تقريب الفواصل العشرية قبل تصديرها للسيرفر (Rounding to 3 decimals) +++
      'price_per_carton': double.parse(pricePerCarton.toStringAsFixed(3)),
      'price_per_pack': double.parse(pricePerPack.toStringAsFixed(3)),
      'packs_per_carton': packsPerCarton,
      'starting_cartons': startingCartons,
      'starting_packs': startingPacks,
      'sold_cartons': soldCartons,
      'sold_packs': soldPacks,
      'current_cartons': currentCartons,
      'current_packs': currentPacks,
    };
  }

  // +++ إخبار الـ BLoC بكيفية المقارنة لمنع إعادة البناء العبثي للواجهة +++
  @override
  List<Object?> get props => [
    id, name, pricePerCarton, pricePerPack,
    packsPerCarton, startingCartons, startingPacks, 
    soldCartons, soldPacks, currentCartons, currentPacks,
  ];
}
