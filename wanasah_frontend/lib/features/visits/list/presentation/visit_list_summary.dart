import 'package:flutter/material.dart';

import '../application/visit_list_filter.dart';
import '../application/visit_list_read_model.dart';
import 'visit_list_strings.dart';

class VisitListSummary extends StatelessWidget {
  const VisitListSummary({
    required this.counts,
    required this.filter,
    required this.onFilterChanged,
    super.key,
  });

  final VisitRouteCounts counts;
  final VisitListFilter filter;
  final ValueChanged<VisitListFilter> onFilterChanged;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final filters = VisitListFilter.values;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 8),
      child: ToggleButtons(
        isSelected: filters.map((value) => value == filter).toList(),
        onPressed: (index) => onFilterChanged(filters[index]),
        borderRadius: BorderRadius.circular(8),
        constraints: BoxConstraints(
          minHeight: 40,
          minWidth: (MediaQuery.sizeOf(context).width - 32) / 3.1,
        ),
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              visitListString(
                VisitListStringKey.filterAll,
                localeCode: locale,
                values: <String, Object>{'count': counts.total},
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              visitListString(
                VisitListStringKey.filterCompleted,
                localeCode: locale,
                values: <String, Object>{'count': counts.completed},
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              visitListString(
                VisitListStringKey.filterPending,
                localeCode: locale,
                values: <String, Object>{'count': counts.pending},
              ),
            ),
          ),
        ],
      ),
    );
  }
}
