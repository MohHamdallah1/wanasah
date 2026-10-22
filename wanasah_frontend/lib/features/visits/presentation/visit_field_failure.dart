import 'package:flutter/material.dart';
import '../../../core/network/api_failure.dart';
import 'visit_field_strings.dart';

enum VisitFailureCategory { connectivity, authorization, business }

VisitFailureCategory visitFailureCategory(ApiFailure failure) {
  if (failure.kind != ApiFailureKind.serverResponse ||
      failure.status == null || failure.status! >= 500 ||
      failure.status == 408 || failure.status == 429) {
    return VisitFailureCategory.connectivity;
  }
  if (failure.status == 401 || failure.status == 403) {
    return VisitFailureCategory.authorization;
  }
  return VisitFailureCategory.business;
}

/// Context stays in the original typed failure for diagnostics. Never render
/// arbitrary context, tokens, server internals or use message text as authority.
class VisitFieldFailurePanel extends StatelessWidget {
  const VisitFieldFailurePanel({super.key, this.failure, this.issue = 'contract'});
  final ApiFailure? failure;
  final String issue;

  @override
  Widget build(BuildContext context) {
    final strings = VisitFieldStrings.of(context);
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text(strings.t(failure == null ? issue : visitFailureCategory(failure!).name)),
      if (failure != null)
        SelectableText([failure!.status, failure!.code, failure!.requestId]
          .where((value) => value != null).join(' · ')),
    ]);
  }
}

Future<void> showVisitFieldFailure(BuildContext context,
  {ApiFailure? failure, String issue = 'contract'}) =>
    showDialog<void>(context: context, builder: (context) => AlertDialog(
      content: VisitFieldFailurePanel(failure: failure, issue: issue),
      actions: [TextButton(onPressed: () => Navigator.pop(context),
        child: Text(VisitFieldStrings.of(context).t('close')))],
    ));
