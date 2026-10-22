import 'package:flutter/material.dart';
import '../../application/commercial/read_commercial_readiness.dart';
import '../../application/commercial/commercial_readiness_outcome.dart';
import '../visit_field_strings.dart';
import '../visit_field_failure.dart';

class VisitCommercialBlocker extends StatelessWidget {
  const VisitCommercialBlocker({super.key, required this.outcome});
  final CommercialActionRequired outcome;
  @override
  Widget build(BuildContext context) {
    final strings = VisitFieldStrings.of(context);
    final actionKey = outcome.requiredAction == 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION'
      ? 'setJurisdiction' : 'contactBackoffice';
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text(strings.t('commercial')),
      Text(strings.t(actionKey)),
      SelectableText(outcome.code),
    ]);
  }
}

Future<CommercialReady?> checkVisitCommercialReadiness(BuildContext context,
  {required int visitId, required ReadCommercialReadiness read}) async {
  final result = await read.execute(visitId);
  if (!context.mounted) return null;
  switch (result) {
    case CommercialReady():
      return result;
    case CommercialActionRequired():
      await showDialog<void>(context: context, builder: (context) => AlertDialog(
        content: VisitCommercialBlocker(outcome: result),
        actions: [TextButton(onPressed: () => Navigator.pop(context),
          child: Text(VisitFieldStrings.of(context).t('close')))],
      ));
    case CommercialReadinessFailed():
      await showVisitFieldFailure(context, failure: result.failure);
    case CommercialReadinessInvalidResponse():
      await showVisitFieldFailure(context);
  }
  return null;
}
