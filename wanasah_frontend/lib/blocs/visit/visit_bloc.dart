// File: lib/blocs/visit/visit_bloc.dart

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';
import 'dart:developer' as developer;
import 'dart:convert'; // +++ النسف المعماري: استيراد مكتبة فك التشفير +++
import 'package:dio/dio.dart';
import '../../core/db/local_database.dart';
import '../../models/product_model.dart';
import '../../models/cart_item_model.dart';
import '../../repositories/sync_repository.dart'; // +++ للتعامل مع الخزنة وحفظ الفاتورة +++

// ============================================================================
// 1. الأوامر (Events)
// ============================================================================
abstract class VisitEvent extends Equatable {
  const VisitEvent();
  @override
  List<Object?> get props => [];
}

class LoadVisitCatalog extends VisitEvent {
  final double shopBalance;
  const LoadVisitCatalog(this.shopBalance);
  @override
  List<Object?> get props => [shopBalance];
}

// +++ النسف المعماري: حدث استعادة الزيارة المكتملة من SQLite (الزيارة العمياء) +++
class LoadCompletedVisitData extends VisitEvent {
  final String? cartItemsJson;
  final String? returnsJson;
  final double cashCollected;
  final double debtPaid;
  final String? notes; // +++ حماية من الـ Null +++

  const LoadCompletedVisitData({
    this.cartItemsJson,
    this.returnsJson,
    required this.cashCollected,
    required this.debtPaid,
    required this.notes,
  });

  @override
  List<Object?> get props => [
    cartItemsJson,
    returnsJson,
    cashCollected,
    debtPaid,
    notes,
  ];
}

class AddOrUpdateCartItem extends VisitEvent {
  final CartItemModel item;
  const AddOrUpdateCartItem(this.item);
  @override
  List<Object?> get props => [item];
}

class RemoveCartItem extends VisitEvent {
  final int productVariantId;
  const RemoveCartItem(this.productVariantId);
  @override
  List<Object?> get props => [productVariantId];
}

class UpdateCashCollected extends VisitEvent {
  final double amount;
  const UpdateCashCollected(this.amount);
  @override
  List<Object?> get props => [amount];
}

// +++ سد ثغرة التضارب المالي: حدث لتحديث الدين اللحظي +++
class UpdateDebtPaid extends VisitEvent {
  final double amount;
  const UpdateDebtPaid(this.amount);
  @override
  List<Object?> get props => [amount];
}

// +++ إضافة الحدث المفقود الذي سيوجه الضربة النهائية +++
class SubmitVisit extends VisitEvent {
  final int visitId;
  final String outcome;
  final String? notes;
  final double debtPaid; // +++ إضافة حقل سداد الدين +++
  const SubmitVisit({
    required this.visitId,
    required this.outcome,
    required this.debtPaid,
    this.notes,
  });
  @override
  List<Object?> get props => [visitId, outcome, debtPaid, notes];
}

// ============================================================================
// 2. الحالات (States)
// ============================================================================
abstract class VisitState extends Equatable {
  const VisitState();
  @override
  List<Object?> get props => [];
}

class VisitLoading extends VisitState {}

// +++ حالة لعرض رسائل SnackBar عند الأخطاء اللحظية أو الجسيمة +++
class VisitError extends VisitState {
  final String message;
  const VisitError(this.message);
  @override
  List<Object?> get props => [message];
}

// +++ حالة النجاح لإغلاق الشاشة +++
class VisitSubmissionSuccess extends VisitState {}

class VisitReady extends VisitState {
  final List<ProductModel> catalog;
  final List<CartItemModel> cart;
  final double shopBalance;
  final double cashCollected;
  final double debtPaid;
  final String? notes; 

  const VisitReady({
    required this.catalog,
    this.cart = const [],
    required this.shopBalance,
    this.cashCollected = 0.0,
    this.debtPaid = 0.0,
    this.notes, 
  });

  double get totalSales => cart.fold(0.0, (sum, item) => sum + item.totalSalePrice);
  double get totalReturns => cart.fold(0.0, (sum, item) => sum + item.totalReturnPrice);
  double get netInvoice => totalSales;
  double get expectedNewBalance => (shopBalance + netInvoice) - cashCollected - debtPaid;

  VisitReady copyWith({
    List<ProductModel>? catalog,
    List<CartItemModel>? cart,
    double? shopBalance,
    double? cashCollected,
    double? debtPaid,
    String? notes, 
  }) {
    return VisitReady(
      catalog: catalog ?? this.catalog,
      cart: cart ?? this.cart,
      shopBalance: shopBalance ?? this.shopBalance,
      cashCollected: cashCollected ?? this.cashCollected,
      debtPaid: debtPaid ?? this.debtPaid,
      notes: notes ?? this.notes, 
    );
  }

  @override
  List<Object?> get props => [catalog, cart, shopBalance, cashCollected, debtPaid, notes];
}

// ============================================================================
// 3. العقل المدبر (Bloc)
// ============================================================================
class VisitBloc extends Bloc<VisitEvent, VisitState> {
  final LocalDatabase _db;
  final SyncRepository _syncRepo;

  VisitBloc({LocalDatabase? db, SyncRepository? syncRepo})
    : _db = db ?? LocalDatabase.instance,
      _syncRepo = syncRepo ?? SyncRepository(),
      super(VisitLoading()) {
    on<LoadVisitCatalog>(_onLoadCatalog);
    on<LoadCompletedVisitData>(
      _onLoadCompletedVisitData,
    ); // +++ تسجيل المستمع +++
    on<AddOrUpdateCartItem>(_onAddOrUpdateCartItem);
    on<RemoveCartItem>(_onRemoveCartItem);
    on<UpdateCashCollected>(_onUpdateCashCollected);
    on<UpdateDebtPaid>(_onUpdateDebtPaid); // +++ تسجيل المستمع الجديد +++
    on<SubmitVisit>(_onSubmitVisit); // +++ تسجيل حدث الإنهاء +++
  }

  Future<void> _onLoadCatalog(
    LoadVisitCatalog event,
    Emitter<VisitState> emit,
  ) async {
    try {
      // +++ حل خطأ التحويل النوعي (Type Casting) +++
      final List<Map<String, dynamic>> rawProducts = await _db.getProducts();
      final List<ProductModel> products =
          rawProducts.map((p) => ProductModel.fromJson(p)).toList();

      emit(VisitReady(catalog: products, shopBalance: event.shopBalance));
    } catch (e) {
      developer.log('[VisitBloc] Error loading catalog: $e');
      // +++ حل مشكلة التحميل اللانهائي بإرسال حالة خطأ +++
      emit(
        const VisitError(
          'حدث خطأ أثناء تحميل المنتجات. الرجاء المحاولة لاحقاً.',
        ),
      );
    }
  }

  // +++ بناء السلة من نصوص الـ JSON المحفوظة محلياً (المزامنة العكسية) +++
  Future<void> _onLoadCompletedVisitData(
    LoadCompletedVisitData event,
    Emitter<VisitState> emit,
  ) async {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    try {
      List<CartItemModel> restoredCart = [];

      // 1. استعادة المبيعات وإعادة المخزون المحجوز للمتاح
      if (event.cartItemsJson != null && event.cartItemsJson!.isNotEmpty && event.cartItemsJson != 'null') {
        final dynamic decodedCart = jsonDecode(event.cartItemsJson!);
        if (decodedCart is List) {
          for (var item in decodedCart) {
            final int pId = int.tryParse(item['product_variant_id']?.toString() ?? '') ?? 0;
            if (pId == 0) continue;

            final int pIndex = currentState.catalog.indexWhere((p) => p.id == pId);
            if (pIndex < 0) continue; 
            final product = currentState.catalog[pIndex];

            // +++ الكي الجراحي: إضافة المحجوز مسبقاً للمخزون الحالي ليتمكن المندوب من التعديل +++
            final int safePpc = product.packsPerCarton > 0 ? product.packsPerCarton : 1;
            final int savedC = item['quantity'] ?? 0;
            final int savedP = item['packs_quantity'] ?? 0;
            final int savedSc = item['sample_quantity'] ?? 0;
            final int savedSp = item['sample_packs_quantity'] ?? 0;

            final int totalSavedPacks = ((savedC + savedSc) * safePpc) + savedP + savedSp;
            final int totalCurrentPacks = (product.currentCartons * safePpc) + product.currentPacks;
            final int combinedPacks = totalCurrentPacks + totalSavedPacks;

            restoredCart.add(
              CartItemModel(
                productVariantId: pId,
                name: product.name,
                pricePerCarton: product.pricePerCarton,
                pricePerPack: product.pricePerPack,
                packsPerCarton: product.packsPerCarton,
                availableCartons: combinedPacks ~/ safePpc,
                availablePacks: combinedPacks % safePpc,
                cartons: savedC,
                packs: savedP,
                sampleCartons: savedSc,
                samplePacks: savedSp,
                sampleReason: item['sample_reason'] ?? '',
              ),
            );
          }
        }
      }

      // 2. استعادة المرتجعات وإعادة المخزون المحجوز للمتاح
      if (event.returnsJson != null && event.returnsJson!.isNotEmpty && event.returnsJson != 'null') {
        final dynamic decodedReturns = jsonDecode(event.returnsJson!);
        if (decodedReturns is List) {
          for (var ret in decodedReturns) {
            final int pId = int.tryParse(ret['product_variant_id']?.toString() ?? '') ?? 0;
            if (pId == 0) continue;

            final String type = ret['return_type'] ?? '';
            final int qty = ret['quantity'] ?? 0;
            final int pQty = ret['packs_quantity'] ?? 0;

            int rfC = type == 'Factory_Defect' ? qty : 0;
            int rfP = type == 'Factory_Defect' ? pQty : 0;
            int reC = type == 'Expired' ? qty : 0;
            int reP = type == 'Expired' ? pQty : 0;

            final existingItemIndex = restoredCart.indexWhere((i) => i.productVariantId == pId);

            if (existingItemIndex >= 0) {
              final currentItem = restoredCart[existingItemIndex];
              
              // +++ الكي الجراحي: إضافة التالف المحجوز للمخزون الحالي +++
              final int safePpc = currentItem.packsPerCarton > 0 ? currentItem.packsPerCarton : 1;
              final int returnsPacks = ((rfC + reC) * safePpc) + rfP + reP;
              final int currentAvailablePacks = (currentItem.availableCartons * safePpc) + currentItem.availablePacks;
              final int combinedPacks = currentAvailablePacks + returnsPacks;

              restoredCart[existingItemIndex] = currentItem.copyWith(
                availableCartons: combinedPacks ~/ safePpc,
                availablePacks: combinedPacks % safePpc,
                returnFactoryCartons: currentItem.returnFactoryCartons + rfC,
                returnFactoryPacks: currentItem.returnFactoryPacks + rfP,
                returnExpiredCartons: currentItem.returnExpiredCartons + reC,
                returnExpiredPacks: currentItem.returnExpiredPacks + reP,
              );
            } else {
              final int pIndex = currentState.catalog.indexWhere((p) => p.id == pId);
              if (pIndex < 0) continue;
              final product = currentState.catalog[pIndex];
              
              // +++ الكي الجراحي: إضافة التالف المحجوز للمخزون الحالي +++
              final int safePpc = product.packsPerCarton > 0 ? product.packsPerCarton : 1;
              final int returnsPacks = ((rfC + reC) * safePpc) + rfP + reP;
              final int totalCurrentPacks = (product.currentCartons * safePpc) + product.currentPacks;
              final int combinedPacks = totalCurrentPacks + returnsPacks;

              restoredCart.add(
                CartItemModel(
                  productVariantId: pId,
                  name: product.name,
                  pricePerCarton: product.pricePerCarton,
                  pricePerPack: product.pricePerPack,
                  packsPerCarton: product.packsPerCarton,
                  availableCartons: combinedPacks ~/ safePpc,
                  availablePacks: combinedPacks % safePpc,
                  returnFactoryCartons: rfC,
                  returnFactoryPacks: rfP,
                  returnExpiredCartons: reC,
                  returnExpiredPacks: reP,
                ),
              );
            }
          }
        }
      }

      emit(
        currentState.copyWith(
          cart: restoredCart,
          cashCollected: event.cashCollected,
          debtPaid: event.debtPaid,
          notes: event.notes, 
        ),
      );
    } catch (e) {
      developer.log('[VisitBloc] Error restoring completed visit: $e');
      emit(const VisitError('فشل استعادة بيانات الفاتورة السابقة.'));
      emit(currentState); 
    }
  }

  void _onAddOrUpdateCartItem(
    AddOrUpdateCartItem event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    // +++ F-04: درع الـ Race Condition - التحقق من الكمية داخل الـ BLoC بشكل قطعي لمنع تجاوز المخزون عند النقر السريع +++
    int safePpc = event.item.packsPerCarton > 0 ? event.item.packsPerCarton : 1;
    // +++ تضمين المرتجعات (بما أنها استبدال) في درع السباق لمنع عجز المخزون الفعلي في سيارة المندوب +++
    int totalRequested = (event.item.cartons * safePpc) + event.item.packs + 
                         (event.item.sampleCartons * safePpc) + event.item.samplePacks +
                         (event.item.returnFactoryCartons * safePpc) + event.item.returnFactoryPacks +
                         (event.item.returnExpiredCartons * safePpc) + event.item.returnExpiredPacks;
    int totalAvailable = (event.item.availableCartons * safePpc) + event.item.availablePacks;
    
    if (totalRequested > totalAvailable) {
      developer.log('[VisitBloc] Inventory Blocked (Race Condition Shield): Not enough stock for ${event.item.name}');
      // +++ إطلاق الخطأ كـ State مستقلة لتصطادها الواجهة وتظهر SnackBar فوراً +++
      emit(VisitError('عفواً، كمية ${event.item.name} المطلوبة لا تكفي بالسيارة.'));
      emit(currentState); // العودة للحالة الجاهزة لمنع تجميد الشاشة
      return;
    }

    final updatedCart = List<CartItemModel>.from(currentState.cart);
    final index = updatedCart.indexWhere(
      (i) => i.productVariantId == event.item.productVariantId,
    );

    // +++ C8: النسف المعماري - تصفية العناصر صفرية الكمية جراحياً داخل الـ BLoC +++
    // إذا كانت جميع الكميات صفر، نحذف العنصر من السلة تماماً
    final bool hasZeroQuantities = 
        event.item.cartons == 0 &&
        event.item.packs == 0 &&
        event.item.sampleCartons == 0 &&
        event.item.samplePacks == 0 &&
        event.item.returnFactoryCartons == 0 &&
        event.item.returnFactoryPacks == 0 &&
        event.item.returnExpiredCartons == 0 &&
        event.item.returnExpiredPacks == 0;

    if (hasZeroQuantities) {
      // حذف العنصر إذا كان موجوداً
      if (index >= 0) {
        updatedCart.removeAt(index);
      }
      // لا نضيف العنصر صفر الكمية
    } else {
      if (index >= 0) {
        updatedCart[index] = event.item; // تحديث
      } else {
        updatedCart.add(event.item); // إضافة جديدة
      }
    }

    emit(currentState.copyWith(cart: updatedCart));
  }

  void _onRemoveCartItem(RemoveCartItem event, Emitter<VisitState> emit) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    final updatedCart =
        currentState.cart
            .where((i) => i.productVariantId != event.productVariantId)
            .toList();
    emit(currentState.copyWith(cart: updatedCart));
  }

  void _onUpdateCashCollected(
    UpdateCashCollected event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(currentState.copyWith(cashCollected: event.amount));
  }

  void _onUpdateDebtPaid(UpdateDebtPaid event, Emitter<VisitState> emit) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(currentState.copyWith(debtPaid: event.amount));
  }

  // +++ الحدث المعماري الأضخم: تجهيز الفاتورة وإرسالها للخزنة السرية +++
  Future<void> _onSubmitVisit(
    SubmitVisit event,
    Emitter<VisitState> emit,
  ) async {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(VisitLoading()); // إظهار مؤشر التحميل أثناء التشفير والحفظ

    try {
      // 1. تجميع المبيعات والعينات (الصنف الذي فيه مبيع أو عينة يذهب لـ cart_items ليفهمه السيرفر)
      final List<Map<String, dynamic>> cartItems =
          currentState.cart
              .where(
                (i) =>
                    i.cartons > 0 ||
                    i.packs > 0 ||
                    i.sampleCartons > 0 ||
                    i.samplePacks > 0,
              )
              .map(
                (i) => {
                  'product_variant_id': i.productVariantId,
                  'quantity': i.cartons,
                  'packs_quantity':
                      i.packs, // +++ الكي الجراحي: مطابقة اسم الحقل مع السيرفر +++
                  'sample_quantity': i.sampleCartons, // +++ الكي الجراحي +++
                  'sample_packs_quantity':
                      i.samplePacks, // +++ الكي الجراحي +++
                  'sample_reason': i.sampleReason,
                },
              )
              .toList();

      // 2. تجميع المرتجعات والتوالف (النسف المعماري: تفكيك الـ List المدمجة)
      final List<Map<String, dynamic>> returns = [];
      for (var item in currentState.cart) {
        if (item.returns.isNotEmpty) {
          for (var ret in item.returns) {
            returns.add({
              'product_variant_id': item.productVariantId,
              'quantity': ret['cartons'] ?? 0,
              'packs_quantity': ret['packs'] ?? 0,
              'return_type': ret['type'] ?? '',
            });
          }
        }
      }

      // 3. بناء الـ Payload المطابق 100% للسيرفر بعد التحديث
      final payload = <String, dynamic>{
        'visit_id': event.visitId, // +++ الكي الجراحي: حقن الـ ID بوضوح ليتعرف التطبيق على مسودته +++
        'visitId': event.visitId, // ضمان التوافقية
        'outcome': event.outcome,
        'notes': event.notes ?? '',
      };

      // +++ التوافق المعماري (I-01 Shield): عزل الأموال والبضاعة عن الزيارات المؤجلة لمنع الـ 400 +++
      if (event.outcome == 'Sale' || event.outcome == 'NoSale') {
        payload['cash_collected'] = currentState.cashCollected;
        payload['debt_paid'] = event.debtPaid;
        
        if (cartItems.isNotEmpty) payload['cart_items'] = cartItems;
        if (returns.isNotEmpty) payload['returns'] = returns;

        if (event.outcome == 'NoSale') {
          payload['no_sale_reason'] = event.notes ?? '';
        }
      }

      // 5. الضرب المباشر على الخزنة السرية (SyncRepository)
      await _syncRepo.saveInvoice(visitId: event.visitId, payload: payload);

      // إعلان نجاح العملية لتغلق الشاشة
      emit(VisitSubmissionSuccess());
    } catch (e) {
      developer.log('[VisitBloc] Error submitting visit: $e');
      String errorMsg = 'حدث خطأ أثناء حفظ الفاتورة في الخزنة المحلية.';

      // +++ الكيّ الجراحي: التقاط رسالة الرفض الصريحة من السيرفر وعرضها للمندوب +++
      if (e is DioException &&
          e.response?.data != null &&
          e.response!.data is Map) {
        // +++ التوافق مع Pydantic/FastAPI لمنع ضياع سبب الرفض +++
        errorMsg =
            e.response!.data['message'] ?? e.response!.data['detail'] ??
            'رفض السيرفر العملية (${e.response!.statusCode})';
      }

      // +++ B1: إجبار الواجهة على كسر حالة التحميل الوهمي عبر إطلاق VisitError مستقل +++
      // هذا يضمن أن BlocListener في الواجهة سيلتقط الخطأ ويعرض SnackBar ويفك القفل
      emit(VisitError(errorMsg));
      // +++ إعادة إرسال الحالة السابقة فوراً لضمان عدم ضياع سلة المندوب +++
      emit(currentState);
    }
  }

  // Step 4.4b: Memory leak shield — reserved for future Stream/Timer disposal
  // ignore: unnecessary_overrides
}
