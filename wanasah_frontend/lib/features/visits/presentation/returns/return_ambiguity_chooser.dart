import 'package:flutter/material.dart';
import '../../application/returns/return_resolution_outcome.dart';
import '../../domain/returns/return_evidence.dart';
import '../visit_field_strings.dart';

/// Only sanitized Backend human evidence enters this widget. No default choice.
class ReturnAmbiguityChooser extends StatefulWidget {
  const ReturnAmbiguityChooser({super.key, required this.pending, required this.productName});
  final ReturnEvidenceRequired pending;
  final String productName;
  @override
  State<ReturnAmbiguityChooser> createState() => _ReturnAmbiguityChooserState();
}

class _ReturnAmbiguityChooserState extends State<ReturnAmbiguityChooser> {
  int? _selected;
  late final _fields = {
    for (final field in widget.pending.ambiguity.requiredEvidence)
      field.code: TextEditingController(),
  };
  @override
  void dispose() {
    for (final field in _fields.values) { field.dispose(); }
    super.dispose();
  }

  ReturnEvidence? _evidence() {
    final required = widget.pending.ambiguity.requiredEvidence;
    final Map<String, dynamic> values;
    if (widget.pending.ambiguity.choices.isNotEmpty) {
      if (_selected == null) return null;
      final choice = widget.pending.ambiguity.choices[_selected!].toJson();
      values = {for (final field in required) field.code: choice[field.code]};
    } else {
      values = {for (final field in required) field.code: _fields[field.code]!.text};
    }
    try { return ReturnEvidence.fromJson(values); }
    on FormatException { return null; }
  }

  @override
  Widget build(BuildContext context) {
    final strings = VisitFieldStrings.of(context);
    final pending = widget.pending;
    return AlertDialog(
      title: Text(strings.t('ambiguity')),
      content: SizedBox(width: double.maxFinite, child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(widget.productName),
          if (pending.ambiguity.choices.isNotEmpty)
            for (var index = 0; index < pending.ambiguity.choices.length; index++)
              RadioListTile<int>(
                value: index, groupValue: _selected,
                onChanged: (value) => setState(() => _selected = value),
                title: Text([
                  for (final field in pending.ambiguity.requiredEvidence)
                    '${strings.t(field.code)}: ${pending.ambiguity.choices[index].toJson()[field.code]}',
                ].join('\n')),
              )
          else
            for (final field in pending.ambiguity.requiredEvidence)
              TextField(
                controller: _fields[field.code],
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(labelText: strings.t(field.code),
                  hintText: field == ReturnEvidenceField.lotNumber
                    ? null : strings.t('dateHint')),
              ),
          // Original correlation evidence; context is never rendered wholesale.
          SelectableText([pending.failure.code, pending.failure.requestId]
            .whereType<String>().join(' · ')),
        ]),
      )),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context),
          child: Text(strings.t('cancel'))),
        FilledButton(
          onPressed: _evidence() == null ? null :
            () => Navigator.pop(context, _evidence()),
          child: Text(strings.t('continue')),
        ),
      ],
    );
  }
}
