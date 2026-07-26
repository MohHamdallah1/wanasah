// File: lib/models/product_model.dart
import 'package:equatable/equatable.dart';
// +++ النسف المعماري للأداء (Equatable Enforcement): جعل الموديل قابلاً للمقارنة الذكية +++
class ProductModel extends Equatable {
  final int id;
  final String name;
  final double pricePerCarton;
  final double pricePerPack;
  final int packsPerCarton;
  final int
  startingCartons; // +++ الحقل الجديد لحفظ كمية الاستلام (بضاعة أول المدة) +++
  final int currentCartons;
  final int currentPacks;

  const ProductModel({
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
      // +++ الدرع النخبوي (Type-Safe Shield): لا ثقة بأي نوع بيانات قادم من السيرفر أو SQLite +++
      id: int.tryParse((json['id'] ?? json['product_variant_id'])?.toString() ?? '0') ?? 0,
      name:
          json['name']?.toString() ??
          json['product_name']?.toString() ??
          json['variant_name']?.toString() ??
          'منتج غير معروف',
      
      // +++ نسف قنبلة الـ toDouble() التي تسقط التطبيق فوراً إذا عاد السعر كنص +++
      pricePerCarton: double.tryParse(json['price_per_carton']?.toString() ?? '0') ?? 0.0,
      pricePerPack: double.tryParse(json['price_per_pack']?.toString() ?? '0') ?? 0.0,
      
      // +++ حماية الحسابات الكمية من خطأ الـ (String is not a subtype of int) +++
      packsPerCarton: int.tryParse(json['packs_per_carton']?.toString() ?? '1') ?? 1,
      
      // +++ قراءة الاستلام من السيرفر أو من SQLite بأمان مطلق +++
      startingCartons: int.tryParse(json['starting_cartons']?.toString() ?? '0') ?? 0,
      currentCartons: int.tryParse((json['current_cartons'] ?? json['remaining_cartons'])?.toString() ?? '0') ?? 0,
      currentPacks: int.tryParse((json['current_packs'] ?? json['remaining_packs'])?.toString() ?? '0') ?? 0,
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
    // +++ إخبار الـ BLoC بكيفية المقارنة لمنع إعادة البناء العبثي للواجهة +++
  @override
  List<Object?> get props => [
    id, name, pricePerCarton, pricePerPack,
    packsPerCarton, startingCartons, currentCartons, currentPacks,
  ];

}
