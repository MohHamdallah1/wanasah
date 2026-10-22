import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../application/visit_list_read_model.dart';
import 'visit_list_strings.dart';

class VisitCard extends StatelessWidget {
  const VisitCard({
    required this.row,
    required this.onOpen,
    required this.onMap,
    super.key,
  });

  final VisitListRow row;
  final VoidCallback onOpen;
  final VoidCallback onMap;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final visual = _visual();
    final amount = NumberFormat('0.00', 'en_US').format(row.shopBalance);

    return Card(
      key: ValueKey(row.id),
      elevation: row.isCompleted ? 0 : 2,
      margin: const EdgeInsets.only(bottom: 12),
      color: visual.background,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: visual.border, width: 1.2),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        splashColor: Colors.transparent,
        highlightColor: Colors.transparent,
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: visual.iconBackground,
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  visual.icon,
                  color: visual.iconColor,
                  size: 26,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${row.sequence}. ${row.shopName}',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 10,
                      runSpacing: 6,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: visual.statusColor,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            _statusLabel(locale),
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                        Text(
                          visitListString(
                            VisitListStringKey.balanceLabel,
                            localeCode: locale,
                            values: <String, Object>{'amount': amount},
                          ),
                          style: TextStyle(
                            color: Colors.grey.shade700,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(
                  Icons.map_outlined,
                  color: Colors.blue,
                  size: 28,
                ),
                tooltip: visitListString(
                  VisitListStringKey.mapTooltip,
                  localeCode: locale,
                ),
                onPressed: onMap,
              ),
            ],
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

  _VisitCardVisual _visual() {
    if (row.isCompleted) {
      return _VisitCardVisual(
        icon: Icons.check_circle,
        iconColor: Colors.green,
        border: Colors.green.shade300,
        background: Colors.green.shade50.withValues(alpha: 0.4),
        iconBackground: Colors.green.shade100,
        statusColor: Colors.green,
      );
    }

    if (row.isAttempted) {
      return _VisitCardVisual(
        icon: Icons.history,
        iconColor: Colors.orange,
        border: Colors.orange.shade300,
        background:
            row.isEmergency ? Colors.red.shade50 : Colors.white,
        iconBackground:
            row.isEmergency ? Colors.red.shade100 : Colors.blue.shade50,
        statusColor: Colors.orange,
      );
    }

    if (row.isEmergency) {
      return _VisitCardVisual(
        icon: Icons.warning_amber_rounded,
        iconColor: Colors.red.shade600,
        border: Colors.red.shade300,
        background: Colors.red.shade50,
        iconBackground: Colors.red.shade100,
        statusColor: Colors.blueGrey,
      );
    }

    return _VisitCardVisual(
      icon: Icons.storefront,
      iconColor: Colors.blueGrey,
      border: Colors.grey.shade300,
      background: Colors.white,
      iconBackground: Colors.blue.shade50,
      statusColor: Colors.blueGrey,
    );
  }
}

class _VisitCardVisual {
  const _VisitCardVisual({
    required this.icon,
    required this.iconColor,
    required this.border,
    required this.background,
    required this.iconBackground,
    required this.statusColor,
  });

  final IconData icon;
  final Color iconColor;
  final Color border;
  final Color background;
  final Color iconBackground;
  final Color statusColor;
}
