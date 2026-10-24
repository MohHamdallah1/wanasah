import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../../../blocs/dashboard/dashboard_state.dart';

/// Existing Home evidence, kept separate from navigation and action ownership.
/// The following Home polish slice can change hierarchy without moving workflows.
class HomeOverview extends StatelessWidget {
  const HomeOverview({
    required this.state,
    required this.workSession,
    required this.pendingTransfers,
    super.key,
  });

  final DashboardLoaded state;
  final Widget workSession;
  final Widget pendingTransfers;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final numbers = NumberFormat.decimalPattern(locale);
    // Preserve locale order/month names with the approved Western digit style.
    final date = DateFormat.yMMMMd(locale)
        .format(DateTime.now())
        .replaceAllMapped(
          RegExp('[٠-٩]'),
          (match) => (match[0]!.codeUnitAt(0) - 0x0660).toString(),
        );
    final money = NumberFormat.currency(
      locale: locale,
      name: 'JOD',
      decimalDigits: 3,
    );
    final l10n = AppLocalizations.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          l10n.greeting(state.driverName),
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(
          l10n.region(state.assignedRegion),
          style: TextStyle(
            fontSize: 17,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          l10n.today(date),
          style: TextStyle(
            fontSize: 15,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const Divider(height: 30, thickness: 1),

        workSession,
        const Divider(height: 30, thickness: 1),
        Text(
          l10n.routeSummary,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        Text(
          l10n.completedVisits(numbers.format(state.completedVisits)),
          style: const TextStyle(fontSize: 16),
        ),
        Text(
          l10n.salesVisits(numbers.format(state.salesInCompleted)),
          style: const TextStyle(fontSize: 16),
        ),
        Text(
          l10n.pendingVisits(numbers.format(state.pendingVisits)),
          style: const TextStyle(fontSize: 16),
        ),
        if (state.offlineVisits > 0)
          Text(
            l10n.offlineVisits(numbers.format(state.offlineVisits)),
            style: TextStyle(
              fontSize: 16,
              color: Theme.of(context).colorScheme.error,
              fontWeight: FontWeight.bold,
            ),
          ),

        const SizedBox(height: 15),
        Text(
          l10n.financialSummary,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                l10n.salesCash(money.format(state.totalSalesCash)),
                style: const TextStyle(fontSize: 16),
              ),
              const SizedBox(height: 4),
              Text(
                l10n.debtCash(
                  numbers.format(state.debtPaymentsCount),
                  money.format(state.totalDebtPaid),
                ),
                style: const TextStyle(fontSize: 16),
              ),
              const SizedBox(height: 4),
              Text(
                l10n.totalCash(money.format(state.totalCashOverall)),
                style: const TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 16,
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: 10),
        pendingTransfers,
      ],
    );
  }
}
