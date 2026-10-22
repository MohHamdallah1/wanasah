import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../blocs/visit/visit_bloc.dart';
import '../../../models/cart_item_model.dart';
import '../../../models/product_model.dart';
import '../domain/returns/return_resolution.dart';
import 'returns/return_reason_quantities.dart';

// ============================================================================
// --- كلاسات وحش الـ POS (The 2026 Accordion UI) ---
// تم عزلها في كلاسات منفصلة لضمان الأداء الصاروخي ومنع تداخل الحالات (Jank)
// ============================================================================

class VisitCatalog extends StatefulWidget {
  final List<ProductModel> catalog;
  final List<CartItemModel> cart;
  final VisitBloc visitBloc;
  final VoidCallback onCartUpdated;
  final VoidCallback onClose; // +++ أمر الإغلاق الآمن +++

  const VisitCatalog({
    super.key,
    required this.catalog,
    required this.cart,
    required this.visitBloc,
    required this.onCartUpdated,
    required this.onClose,
  });

  @override
  State<VisitCatalog> createState() => _VisitCatalogState();
}

class _VisitCatalogState extends State<VisitCatalog> {
  String _searchQuery = '';
  final TextEditingController _searchController = TextEditingController(); // +++ متحكم لتفريغ البحث +++
  // +++ تنظيف الذاكرة: إعدام متغير _drafts الميت +++

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filteredCatalog = widget.catalog.where((p) => p.name.toLowerCase().contains(_searchQuery.toLowerCase())).toList();

    return Expanded( // غلفنا العمود بـ Expanded ليعمل داخل الـ Column الرئيسي
      child: Column(
        children: [
          // سطر البحث (إزالة الإغلاق المكرر والاعتماد على الزر الكبير بالأسفل)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: const BoxDecoration(color: Colors.white, border: Border(bottom: BorderSide(color: Colors.black12))),
            child: Row(
              children: [
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(12)),
                    child: TextField(
                      controller: _searchController,
                      onChanged: (val) => setState(() => _searchQuery = val),
                      decoration: InputDecoration(
                        hintText: 'ابحث عن صنف...',
                        border: InputBorder.none,
                        suffixIcon: _searchQuery.isNotEmpty 
                          ? IconButton(icon: const Icon(Icons.cancel, color: Colors.grey), onPressed: () { _searchController.clear(); setState(() => _searchQuery = ''); }) 
                          : const Icon(Icons.search, color: Colors.blue),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              itemCount: filteredCatalog.length,
              itemBuilder: (context, index) {
                final product = filteredCatalog[index];
                final cartItemIndex = widget.cart.indexWhere((i) => i.productVariantId == product.id);
                final cartItem = cartItemIndex != -1 ? widget.cart[cartItemIndex] : null;

                return _AccordionProductCard(
                  key: ValueKey(product.id), // +++  لـ Bug 6: لمنع انتقال الكميات لمنتج آخر عند البحث +++
                  product: product,
                  cartItem: cartItem,
                  isExpanded: true, 
                  // +++ تنظيف الذاكرة +++
                  onToggle: () {}, 
                  visitBloc: widget.visitBloc,
                  onCartUpdated: widget.onCartUpdated,
                );
              },
            ),
          ),
          _buildMasterConfirmButton(),
        ],
      ),
    );
  }

  Widget _buildMasterConfirmButton() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: Colors.white, boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.05), blurRadius: 10, offset: const Offset(0, -5))]),
      child: SizedBox(
        width: double.infinity,
        height: 55,
        child: ElevatedButton(
          onPressed: () {
             HapticFeedback.heavyImpact();
             widget.onClose(); // +++ يغلق الكاتالوج ويعود للفاتورة فقط دون تدمير الزيارة +++
          },
          style: ElevatedButton.styleFrom(backgroundColor: Colors.blue.shade700, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
          child: const Text('اعتماد الكميات والعودة للفاتورة', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
        ),
      ),
    );
  }
}

class _AccordionProductCard extends StatefulWidget {
  final ProductModel product;
  final CartItemModel? cartItem;
  final bool isExpanded;
  final VoidCallback onToggle;
  final VisitBloc visitBloc;
  final VoidCallback onCartUpdated;

  const _AccordionProductCard({
    super.key, // +++   السماح للكلاس باستقبال الـ Key لمنع الخطأ +++
    required this.product,
    required this.cartItem,
    required this.isExpanded,
    required this.onToggle,
    required this.visitBloc,
    required this.onCartUpdated,
  });

  @override
  State<_AccordionProductCard> createState() => _AccordionProductCardState();
}

class _AccordionProductCardState extends State<_AccordionProductCard> {
  final sCartons = TextEditingController();
  final sPacks = TextEditingController();
  
  // +++ العدادات المباشرة للاستبدال +++
  final rfCartons = TextEditingController(); // تالف مصنع
  final rfPacks = TextEditingController();
  final reCartons = TextEditingController(); // إكسباير
  final rePacks = TextEditingController();
  final rdCartons = TextEditingController();
  final rdPacks = TextEditingController();

  // عينات
  final smpCartons = TextEditingController();
  final smpPacks = TextEditingController();
  final smpReason = TextEditingController();
  
  String? _selectedSampleReason;
  final List<String> _reasonOptions = ['ترويج منتج جديد', 'عينة مجانية للزبائن', 'تعويض ودي للمحل', 'أخرى'];
  bool showExtras = false;

  @override
  void dispose() {
    sCartons.dispose();
    sPacks.dispose();
    rfCartons.dispose();
    rfPacks.dispose();
    reCartons.dispose();
    rePacks.dispose();
    rdCartons.dispose();
    rdPacks.dispose();
    smpCartons.dispose();
    smpPacks.dispose();
    smpReason.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    _syncFromProp();
  }

  @override
  void didUpdateWidget(covariant _AccordionProductCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.product.id != oldWidget.product.id) {
      _syncFromProp();
    }
  }

  void _syncFromProp() {
    // +++   إزالة الإغلاق الإجباري للأكورديون (كان ينهار في وجه المندوب مع كل نقرة) +++
    if (widget.cartItem != null) {
      final item = widget.cartItem!;
      // +++   تحديث النص فقط إذا اختلف لمنع طيران المؤشر (Cursor Hijacking) أثناء الطباعة +++
      void safeUpdate(TextEditingController ctrl, String val) {
        if (ctrl.text != val) ctrl.text = val;
      }
      safeUpdate(sCartons, item.cartons > 0 ? item.cartons.toString() : '');
      safeUpdate(sPacks, item.packs > 0 ? item.packs.toString() : '');
      safeUpdate(rfCartons, item.returnFactoryCartons > 0 ? item.returnFactoryCartons.toString() : '');
      safeUpdate(rfPacks, item.returnFactoryPacks > 0 ? item.returnFactoryPacks.toString() : '');
      safeUpdate(reCartons, item.returnExpiredCartons > 0 ? item.returnExpiredCartons.toString() : '');
      safeUpdate(rePacks, item.returnExpiredPacks > 0 ? item.returnExpiredPacks.toString() : '');
      safeUpdate(rdCartons, item.returnDamagedCartons > 0 ? item.returnDamagedCartons.toString() : '');
      safeUpdate(rdPacks, item.returnDamagedPacks > 0 ? item.returnDamagedPacks.toString() : '');
      safeUpdate(smpCartons, item.sampleCartons > 0 ? item.sampleCartons.toString() : '');
      safeUpdate(smpPacks, item.samplePacks > 0 ? item.samplePacks.toString() : '');
      
      if (item.sampleReason.isNotEmpty) {
        if (_reasonOptions.contains(item.sampleReason)) {
          _selectedSampleReason = item.sampleReason;
        } else {
          _selectedSampleReason = 'أخرى';
          smpReason.text = item.sampleReason;
        }
      } else {
        _selectedSampleReason = null;
      }
    } else {
      sCartons.clear(); sPacks.clear();
      rfCartons.clear(); rfPacks.clear();
      reCartons.clear(); rePacks.clear();
      rdCartons.clear(); rdPacks.clear();
      smpCartons.clear(); smpPacks.clear(); smpReason.clear();
      _selectedSampleReason = null;
    }
  }

  void _commitToBloc() {
    int sc = int.tryParse(sCartons.text) ?? 0;
    int sp = int.tryParse(sPacks.text) ?? 0;
    int rfc = int.tryParse(rfCartons.text) ?? 0;
    int rfp = int.tryParse(rfPacks.text) ?? 0;
    int rec = int.tryParse(reCartons.text) ?? 0;
    int rep = int.tryParse(rePacks.text) ?? 0;
    int smpC = int.tryParse(smpCartons.text) ?? 0;
    int smpP = int.tryParse(smpPacks.text) ?? 0;

    // +++  لـ Bug 3: لا نحذف المنتج فوراً أثناء تصفير الحقل كي لا يضيع تركيز الكيبورد +++
    // سيتم إرساله للـ BLoC بكميات صفرية، وسيتولى البلوك فلترته عند الحفظ النهائي.
    final updatedItem = CartItemModel(
      productVariantId: widget.product.id,
      name: widget.product.name,
      pricePerCarton: widget.product.pricePerCarton,
      pricePerPack: widget.product.pricePerPack,
      packsPerCarton: widget.product.packsPerCarton,
      // +++   استخدام الكمية المتاحة في السلة (التي تشمل المحجوز) بدلاً من الخام +++
      availableCartons: widget.cartItem?.availableCartons ?? widget.product.currentCartons,
      availablePacks: widget.cartItem?.availablePacks ?? widget.product.currentPacks,
      cartons: sc,
      packs: sp,
      returnFactoryCartons: rfc,
      returnFactoryPacks: rfp,
      returnExpiredCartons: rec,
      returnExpiredPacks: rep,
      returnDamagedCartons: int.tryParse(rdCartons.text) ?? 0,
      returnDamagedPacks: int.tryParse(rdPacks.text) ?? 0,
      sampleCartons: smpC,
      samplePacks: smpP,
      sampleReason: _selectedSampleReason == 'أخرى' ? smpReason.text : (_selectedSampleReason ?? ''),
    );

    widget.visitBloc.add(AddOrUpdateCartItem(updatedItem));
    widget.onCartUpdated();
  }

  Widget _buildStepper(String label, TextEditingController controller, {Color iconColor = Colors.blue}) {
    return SizedBox(
      height: 60,
      child: TextField(
        controller: controller,
        onChanged: (_) => _commitToBloc(), 
        textAlign: TextAlign.center,
        keyboardType: TextInputType.number,
        // +++   منع السوالب والفواصل كلياً في حقول الكميات +++
        inputFormatters: [FilteringTextInputFormatter.digitsOnly],
        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 20),
        decoration: InputDecoration(
          labelText: label,
          labelStyle: TextStyle(color: iconColor, fontWeight: FontWeight.bold, fontSize: 13),
          floatingLabelBehavior: FloatingLabelBehavior.always,
          contentPadding: const EdgeInsets.symmetric(vertical: 10),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.grey.shade300)),
          prefixIcon: IconButton(
            icon: const Icon(Icons.remove_circle_outline, color: Colors.red),
            onPressed: () {
              HapticFeedback.lightImpact();
              int curr = int.tryParse(controller.text) ?? 0;
              if (curr > 0) {
                // +++  لـ Bug 9: إبقاء مؤشر الكيبورد في نهاية النص لمنع طفرات الكتابة +++
                final newVal = (curr - 1).toString();
                controller.value = TextEditingValue(text: newVal, selection: TextSelection.collapsed(offset: newVal.length));
                _commitToBloc(); 
              }
            }
          ),
          suffixIcon: IconButton(
            icon: Icon(Icons.add_circle_outline, color: iconColor),
            onPressed: () {
              HapticFeedback.lightImpact();
              int curr = int.tryParse(controller.text) ?? 0;
              final newVal = (curr + 1).toString();
              controller.value = TextEditingValue(text: newVal, selection: TextSelection.collapsed(offset: newVal.length));
              _commitToBloc(); 
            }
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    bool isInCart = widget.cartItem != null;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 400),
      curve: Curves.fastOutSlowIn,
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: showExtras ? Colors.yellow.shade50.withValues(alpha: 0.3) : Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: isInCart ? Colors.green.shade400 : Colors.blue.shade100, width: isInCart ? 2.0 : 1.5),
      ),
      child: Column(
        children: [
          ListTile(
            onTap: () {
              HapticFeedback.selectionClick();
              setState(() => showExtras = !showExtras);
            },
            leading: Icon(isInCart ? Icons.check_circle : Icons.inventory_2_outlined, color: isInCart ? Colors.blue : Colors.grey),
            title: Text(widget.product.name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
            subtitle: Text('المتوفر: ${widget.product.currentCartons} ك | ${widget.product.currentPacks} ح', style: const TextStyle(fontSize: 12)),
            trailing: Icon(showExtras ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down, color: Colors.blue),
          ),
          Padding(
            padding: const EdgeInsets.all(12.0),
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(child: _buildStepper("كراتين المبيع", sCartons, iconColor: Colors.green)),
                    const SizedBox(width: 10),
                    Expanded(child: _buildStepper("حبات المبيع", sPacks, iconColor: Colors.green)),
                  ],
                ),
                AnimatedCrossFade(
                  firstChild: const SizedBox.shrink(),
                  secondChild: Column(
                    children: [
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(color: Colors.blue.shade50.withValues(alpha: 0.3), borderRadius: BorderRadius.circular(15), border: Border.all(color: Colors.blue.shade100)),
                        child: Column(
                          children: [
                            ReturnReasonQuantities(
                              controllers: {
                                FieldReturnType.damaged: (rdCartons, rdPacks),
                                FieldReturnType.expired: (reCartons, rePacks),
                                FieldReturnType.factoryDefect: (rfCartons, rfPacks),
                              },
                              buildQuantity: (label, controller) => _buildStepper(
                                label, controller, iconColor: Colors.orange),
                            ),
                            const Divider(height: 24),
                            Row(
                              children: [
                                Expanded(child: _buildStepper("كراتين العينات (🎁)", smpCartons, iconColor: Colors.purple)),
                                const SizedBox(width: 8),
                                Expanded(child: _buildStepper("حبات العينات (🎁)", smpPacks, iconColor: Colors.purple)),
                              ],
                            ),
                            const SizedBox(height: 8),
                            DropdownButtonFormField<String>(
                              value: _selectedSampleReason,
                              decoration: InputDecoration(
                                hintText: 'اختر سبب صرف العينة (إجباري)',
                                filled: true,
                                fillColor: Colors.white,
                                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                              ),
                              items: _reasonOptions.map((String reason) {
                                return DropdownMenuItem<String>(
                                  value: reason,
                                  child: Text(reason, style: const TextStyle(fontSize: 13)),
                                );
                              }).toList(),
                              onChanged: (String? newValue) {
                                setState(() {
                                  _selectedSampleReason = newValue;
                                  // +++ إضافة الأقواس إجبارياً لإرضاء الـ Linter +++
                                  if (newValue != 'أخرى') {
                                    smpReason.text = newValue ?? '';
                                  } else {
                                    smpReason.clear();
                                  }
                                });
                                _commitToBloc();
                              },
                            ),
                            if (_selectedSampleReason == 'أخرى') ...[
                              const SizedBox(height: 8),
                              TextField(
                                controller: smpReason,
                                onChanged: (_) => _commitToBloc(),
                                decoration: InputDecoration(hintText: 'اكتب السبب بالتفصيل...', filled: true, fillColor: Colors.white, border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)), contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10)),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ],
                  ),
                  crossFadeState: showExtras ? CrossFadeState.showSecond : CrossFadeState.showFirst,
                  duration: const Duration(milliseconds: 300),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}