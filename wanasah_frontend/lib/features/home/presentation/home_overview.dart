import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../app/localization/app_copy.dart';
import '../../../blocs/dashboard/dashboard_state.dart';

/// Existing Home evidence, kept separate from navigation and action ownership.
/// The following Home polish slice can change hierarchy without moving workflows.
class HomeOverview extends StatelessWidget {
  const HomeOverview({
    required this.state,
    required this.workSession,
    required this.pendingTransfers,
    required this.openRoute,
    required this.openCustody,
    super.key,
  });

  final DashboardLoaded state;
  final Widget workSession;
  final Widget pendingTransfers;
  final VoidCallback openRoute;
  final VoidCallback openCustody;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final numbers = NumberFormat.decimalPattern(locale);
    final money = NumberFormat.currency(locale: locale, name: 'JOD', decimalDigits: 3);
    String copy(AppCopyKey key, [Map<String, String> values = const {}]) =>
        AppCopy.of(context, key, values: values);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [

          Text(
            copy(AppCopyKey.greeting, {'name': state.driverName}),
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            copy(AppCopyKey.region, {'region': state.assignedRegion}),
            style: TextStyle(fontSize: 17, color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 8),
          Text(
            copy(AppCopyKey.today, {'date': DateFormat.yMMMMd(locale).format(DateTime.now())}),
            style: TextStyle(fontSize: 15, color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const Divider(height: 30, thickness: 1),

          workSession,
          const Divider(height: 30, thickness: 1),
          Text(copy(AppCopyKey.routeSummary), style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Text(
            copy(AppCopyKey.completedVisits, {'count': numbers.format(state.completedVisits)}),
            style: const TextStyle(fontSize: 16),
          ),
          Text(
            copy(AppCopyKey.salesVisits, {'count': numbers.format(state.salesInCompleted)}),
            style: const TextStyle(fontSize: 16),
          ),
          Text(
            copy(AppCopyKey.pendingVisits, {'count': numbers.format(state.pendingVisits)}),
            style: const TextStyle(fontSize: 16),
          ),
          if (state.offlineVisits > 0)
            Text(
              copy(AppCopyKey.offlineVisits, {'count': numbers.format(state.offlineVisits)}),
              style: TextStyle(
                fontSize: 16,
                color: Theme.of(context).colorScheme.error,
                fontWeight: FontWeight.bold,
              ),
            ),

          const SizedBox(height: 15),
          Text(copy(AppCopyKey.financialSummary), style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  copy(AppCopyKey.salesCash, {'amount': money.format(state.totalSalesCash)}),
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  copy(AppCopyKey.debtCash, {'count': numbers.format(state.debtPaymentsCount), 'amount': money.format(state.totalDebtPaid)}),
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text(
                  copy(AppCopyKey.totalCash, {'amount': money.format(state.totalCashOverall)}),
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 10),
          Center(
            child: ElevatedButton.icon(
              icon: const Icon(Icons.list_alt_rounded),
              label: Text(copy(AppCopyKey.openRoute)),
              onPressed: openRoute,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 30,
                  vertical: 15,
                ),
                textStyle: const TextStyle(fontSize: 16),
              ),
            ),
          ),

          pendingTransfers,
          OutlinedButton.icon(
            onPressed: openCustody,
            icon: const Icon(Icons.inventory_2_outlined),
            label: Text(copy(AppCopyKey.openCustody)),
          ),

      ],
    );
  }
}
