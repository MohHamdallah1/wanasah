import 'package:flutter/material.dart';

import '../../../models/product_model.dart';

class VehicleInventorySection extends StatelessWidget {
  const VehicleInventorySection({
    required this.products,
    super.key,
  });

  final List<ProductModel> products;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 20),
        const Divider(height: 30, thickness: 1),
        Text(
          'مخزون سيارة المندوب:',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        if (products.isEmpty)
          Container(
            padding: const EdgeInsets.all(16.0),
            decoration: BoxDecoration(
              color: Colors.red[50],
              borderRadius: BorderRadius.circular(8.0),
              border: Border.all(color: Colors.red.shade200),
            ),
            child: const Center(
              child: Text(
                'لا يوجد بضاعة في السيارة حالياً.',
                style: TextStyle(
                  fontSize: 16,
                  color: Colors.red,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
        if (products.isNotEmpty)
          ...products.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12.0),
              child: Container(
                padding: const EdgeInsets.all(12.0),
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(8.0),
                  border: Border.all(color: Colors.grey.shade300),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.name,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment:
                          MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          'الاستلام: ${item.startingCartons} كرتونة'
                          "${item.startingPacks > 0 ? ' و ${item.startingPacks} حبة' : ''}",
                          style: const TextStyle(fontSize: 14),
                        ),
                        Text(
                          'المباع: ${item.soldCartons} كرتونة، ${item.soldPacks} حبة',
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.green[700],
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'المتبقي: ${item.currentCartons} كرتونة، ${item.currentPacks} باكيت',
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.bold,
                        color: Colors.blueAccent,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        const SizedBox(height: 20),
      ],
    );
  }
}
