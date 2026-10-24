import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../application/visit_list_read_model.dart';
import 'visit_list_strings.dart';

class VisitCard extends StatelessWidget {
  const VisitCard({
    required this.row,
    required this.onOpen,
    required this.onMap,
    this.isNext = false,
    super.key,
  });

  final VisitListRow row;
  final VoidCallback onOpen;
  final VoidCallback onMap;
  final bool isNext;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final colors = Theme.of(context).colorScheme;
    final visual = _visual(colors);
    final amount = NumberFormat('0.00', 'en_US').format(row.shopBalance);
    final sequence = NumberFormat('00', 'en_US').format(row.sequence);

    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Material(
        key: ValueKey(row.id),
        color: visual.background,
        borderRadius: BorderRadius.circular(18),
        child: InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: onOpen,
          child: Container(
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(18),
              border: Border.all(
                color:
                    isNext
                        ? colors.primary.withValues(alpha: 0.58)
                        : visual.border,
                width: isNext ? 1.4 : 1,
              ),
            ),
            padding: const EdgeInsetsDirectional.fromSTEB(12, 11, 8, 11),
            child: Row(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: visual.accent.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(13),
                  ),
                  child: Text(
                    sequence,
                    textDirection: ui.TextDirection.ltr,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      color: visual.accent,
                      fontWeight: FontWeight.w900,
                      letterSpacing: -0.4,
                    ),
                  ),
                ),
                const SizedBox(width: 11),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 6,
                        runSpacing: 5,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          if (isNext)
                            _MiniBadge(
                              text: visitListString(
                                VisitListStringKey.nextLabel,
                                localeCode: locale,
                              ),
                              foreground: colors.onPrimaryContainer,
                              background: colors.primaryContainer,
                            ),
                          if (row.isEmergency)
                            _MiniBadge(
                              text: visitListString(
                                VisitListStringKey.urgentLabel,
                                localeCode: locale,
                              ),
                              foreground: colors.onErrorContainer,
                              background: colors.errorContainer,
                            ),
                          _MiniBadge(
                            text: _statusLabel(locale),
                            foreground: visual.accent,
                            background: visual.accent.withValues(alpha: 0.08),
                          ),
                        ],
                      ),
                      const SizedBox(height: 7),
                      Text(
                        row.shopName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          color:
                              row.isCompleted
                                  ? colors.onSurfaceVariant
                                  : colors.onSurface,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        visitListString(
                          VisitListStringKey.balanceLabel,
                          localeCode: locale,
                          values: <String, Object>{'amount': amount},
                        ),
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: colors.onSurfaceVariant,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 5),
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      key: ValueKey('visit-map-${row.id}'),
                      constraints: const BoxConstraints(
                        minWidth: 40,
                        minHeight: 40,
                      ),
                      style: IconButton.styleFrom(
                        backgroundColor: colors.surfaceContainerHigh,
                        foregroundColor: colors.onSurfaceVariant,
                      ),
                      icon: const Icon(Icons.location_on_outlined, size: 21),
                      tooltip: visitListString(
                        VisitListStringKey.mapTooltip,
                        localeCode: locale,
                      ),
                      onPressed: onMap,
                    ),
                    Icon(
                      Directionality.of(context) == ui.TextDirection.rtl
                          ? Icons.chevron_left_rounded
                          : Icons.chevron_right_rounded,
                      color: colors.outline,
                      size: 20,
                      semanticLabel: visitListString(
                        VisitListStringKey.openVisitHint,
                        localeCode: locale,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _statusLabel(String locale) {
    final key = switch (row.presentation) {
      VisitExecutionPresentation.completed =>
        VisitListStringKey.statusCompleted,
      VisitExecutionPresentation.pending =>
        VisitListStringKey.statusPending,
      VisitExecutionPresentation.postponed =>
        VisitListStringKey.statusPostponed,
      VisitExecutionPresentation.attempted =>
        row.backendOutcome.trim().toLowerCase() == 'nosale'
            ? VisitListStringKey.statusNoSale
            : VisitListStringKey.statusAttempted,
      VisitExecutionPresentation.other =>
        VisitListStringKey.statusUnknown,
    };

    return visitListString(
      key,
      localeCode: locale,
      values:
          row.presentation == VisitExecutionPresentation.other
              ? <String, Object>{'status': row.backendStatus}
              : const <String, Object>{},
    );
  }

  _VisitCardVisual _visual(ColorScheme colors) {
    if (row.isCompleted) {
      return _VisitCardVisual(
        accent: colors.secondary,
        border: colors.outlineVariant.withValues(alpha: 0.72),
        background: colors.surfaceContainerLowest,
      );
    }

    if (row.isAttempted) {
      return _VisitCardVisual(
        accent: colors.tertiary,
        border: colors.tertiary.withValues(alpha: 0.22),
        background: colors.surfaceContainerLowest,
      );
    }

    if (row.isEmergency) {
      return _VisitCardVisual(
        accent: colors.error,
        border: colors.error.withValues(alpha: 0.24),
        background: colors.surfaceContainerLowest,
      );
    }

    return _VisitCardVisual(
      accent: colors.primary,
      border: colors.outlineVariant.withValues(alpha: 0.78),
      background:
          isNext
              ? colors.primaryContainer.withValues(alpha: 0.16)
              : colors.surfaceContainerLowest,
    );
  }
}

class _MiniBadge extends StatelessWidget {
  const _MiniBadge({
    required this.text,
    required this.foreground,
    required this.background,
  });

  final String text;
  final Color foreground;
  final Color background;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          color: foreground,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _VisitCardVisual {
  const _VisitCardVisual({
    required this.accent,
    required this.border,
    required this.background,
  });

  final Color accent;
  final Color border;
  final Color background;
}
