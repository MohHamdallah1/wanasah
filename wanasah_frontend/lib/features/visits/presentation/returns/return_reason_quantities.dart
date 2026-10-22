import 'package:flutter/material.dart';
import '../../domain/returns/return_resolution.dart';
import '../visit_field_strings.dart';

String visitReturnReasonKey(FieldReturnType reason) => switch (reason) {
  FieldReturnType.damaged => 'damaged',
  FieldReturnType.expired => 'expired',
  FieldReturnType.factoryDefect => 'factoryDefect',
};

class ReturnReasonQuantities extends StatelessWidget {
  const ReturnReasonQuantities({super.key, required this.controllers,
    required this.buildQuantity});
  final Map<FieldReturnType, (TextEditingController, TextEditingController)> controllers;
  final Widget Function(String, TextEditingController) buildQuantity;

  @override
  Widget build(BuildContext context) {
    final strings = VisitFieldStrings.of(context);
    return Column(children: [
      for (final reason in FieldReturnType.values)
        Padding(padding: const EdgeInsets.only(bottom: 12), child: Row(children: [
          Expanded(child: buildQuantity(
            '${strings.t(visitReturnReasonKey(reason))} · ${strings.t('cartons')}',
            controllers[reason]!.$1)),
          const SizedBox(width: 8),
          Expanded(child: buildQuantity(
            '${strings.t(visitReturnReasonKey(reason))} · ${strings.t('packs')}',
            controllers[reason]!.$2)),
        ])),
    ]);
  }
}
