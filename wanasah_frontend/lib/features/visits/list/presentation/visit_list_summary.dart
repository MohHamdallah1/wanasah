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
    final colors = Theme.of(context).colorScheme;
    final filters = VisitListFilter.values;

    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(14, 8, 14, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            visitListString(
              VisitListStringKey.routeOverview,
              localeCode: locale,
              values: <String, Object>{
                'total': counts.total,
                'completed': counts.completed,
                'pending': counts.pending,
              },
            ),
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: colors.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: colors.surfaceContainerHigh.withValues(alpha: 0.62),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(
              children: [
                for (final value in filters) ...[
                  Expanded(
                    child: _FilterSegment(
                      selected: value == filter,
                      label: _labelFor(
                        value,
                        locale,
                        counts,
                      ),
                      onTap: () => onFilterChanged(value),
                    ),
                  ),
                  if (value != filters.last) const SizedBox(width: 3),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _labelFor(
    VisitListFilter value,
    String locale,
    VisitRouteCounts counts,
  ) {
    final (key, count) = switch (value) {
      VisitListFilter.all => (VisitListStringKey.filterAll, counts.total),
      VisitListFilter.completed => (
        VisitListStringKey.filterCompleted,
        counts.completed,
      ),
      VisitListFilter.pending => (
        VisitListStringKey.filterPending,
        counts.pending,
      ),
    };

    return visitListString(
      key,
      localeCode: locale,
      values: <String, Object>{'count': count},
    );
  }
}

class _FilterSegment extends StatelessWidget {
  const _FilterSegment({
    required this.selected,
    required this.label,
    required this.onTap,
  });

  final bool selected;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
        decoration: BoxDecoration(
          color: selected ? colors.surface : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
          boxShadow:
              selected
                  ? [
                    BoxShadow(
                      color: colors.shadow.withValues(alpha: 0.06),
                      blurRadius: 10,
                      offset: const Offset(0, 3),
                    ),
                  ]
                  : null,
        ),
        child: Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
            color: selected ? colors.onSurface : colors.onSurfaceVariant,
            fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
