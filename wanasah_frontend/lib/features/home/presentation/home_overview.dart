import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../blocs/dashboard/dashboard_state.dart';
import '../../../l10n/generated/app_localizations.dart';

/// Home command center. It presents accepted FIELD evidence only; it does not
/// own navigation, accounting authority, Work Session authority or sync logic.
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
    final money = NumberFormat.currency(
      locale: locale,
      name: 'JOD',
      decimalDigits: 3,
    );
    final date = _westernDigits(
      DateFormat.yMMMMd(locale).format(DateTime.now()),
    );
    final progress =
        state.totalVisits <= 0
            ? 0.0
            : (state.completedVisits / state.totalVisits).clamp(0.0, 1.0);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _DayIdentity(
          region: state.assignedRegion,
          date: date,
        ),
        const SizedBox(height: 14),
        workSession,
        const SizedBox(height: 18),
        _RouteProgress(
          progress: progress.toDouble(),
          completed: numbers.format(state.completedVisits),
          total: numbers.format(state.totalVisits),
          remaining: numbers.format(state.pendingVisits),
          sales: numbers.format(state.salesInCompleted),
          offline: numbers.format(state.offlineVisits),
          offlineCount: state.offlineVisits,
        ),
        const SizedBox(height: 16),
        _FinancialPulse(
          total: money.format(state.totalCashOverall),
          sales: money.format(state.totalSalesCash),
          debt: money.format(state.totalDebtPaid),
          debtOperations: numbers.format(state.debtPaymentsCount),
        ),
        if (state.pendingTransfer != null) ...[
          const SizedBox(height: 14),
          pendingTransfers,
        ],
      ],
    );
  }

  String _westernDigits(String value) => value.replaceAllMapped(
    RegExp('[٠-٩]'),
    (match) => (match[0]!.codeUnitAt(0) - 0x0660).toString(),
  );
}

class _DayIdentity extends StatelessWidget {
  const _DayIdentity({
    required this.region,
    required this.date,
  });

  final String region;
  final String date;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _ContextPill(icon: Icons.location_on_outlined, text: region),
            _ContextPill(icon: Icons.calendar_today_outlined, text: date),
          ],
        ),
        const SizedBox(height: 2),
        Divider(color: colors.outlineVariant.withValues(alpha: 0.55)),
      ],
    );
  }
}

class _ContextPill extends StatelessWidget {
  const _ContextPill({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surfaceContainerHigh.withValues(alpha: 0.74),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: 0.70),
        ),
      ),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(11, 7, 12, 7),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: colors.onSurfaceVariant),
            const SizedBox(width: 6),
            Text(
              text,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                fontSize: 12.5,
                color: colors.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RouteProgress extends StatelessWidget {
  const _RouteProgress({
    required this.progress,
    required this.completed,
    required this.total,
    required this.remaining,
    required this.sales,
    required this.offline,
    required this.offlineCount,
  });

  final double progress;
  final String completed;
  final String total;
  final String remaining;
  final String sales;
  final String offline;
  final int offlineCount;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(
          color: colors.outlineVariant.withValues(alpha: 0.82),
        ),
        boxShadow: [
          BoxShadow(
            color: colors.shadow.withValues(alpha: 0.055),
            blurRadius: 22,
            offset: const Offset(0, 9),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: Text(
                  l10n.homeTodayRoute,
                  style: Theme.of(
                    context,
                  ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              Directionality(
                textDirection: ui.TextDirection.ltr,
                child: Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: completed,
                        style: Theme.of(
                          context,
                        ).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w900,
                          color: colors.primary,
                        ),
                      ),
                      TextSpan(
                        text: ' / $total',
                        style: Theme.of(
                          context,
                        ).textTheme.titleMedium?.copyWith(
                          color: colors.onSurfaceVariant,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 9,
              backgroundColor: colors.primary.withValues(alpha: 0.10),
              valueColor: AlwaysStoppedAnimation(colors.primary),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _Metric(
                  value: completed,
                  label: l10n.homeCompletedLabel,
                ),
              ),
              _MetricDivider(color: colors.outlineVariant),
              Expanded(
                child: _Metric(
                  value: remaining,
                  label: l10n.homeRemainingLabel,
                ),
              ),
              _MetricDivider(color: colors.outlineVariant),
              Expanded(
                child: _Metric(value: sales, label: l10n.homeSalesLabel),
              ),
            ],
          ),
          if (offlineCount > 0) ...[
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsetsDirectional.fromSTEB(11, 9, 11, 9),
              decoration: BoxDecoration(
                color: colors.tertiaryContainer.withValues(alpha: 0.52),
                borderRadius: BorderRadius.circular(14),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.schedule_send_outlined,
                    size: 18,
                    color: colors.onTertiaryContainer,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      l10n.homeAwaitingSync(offline),
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: colors.onTertiaryContainer,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        Text(
          value,
          style: Theme.of(
            context,
          ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: colors.onSurfaceVariant,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _MetricDivider extends StatelessWidget {
  const _MetricDivider({required this.color});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 1,
      height: 34,
      margin: const EdgeInsets.symmetric(horizontal: 6),
      color: color.withValues(alpha: 0.72),
    );
  }
}

class _FinancialPulse extends StatelessWidget {
  const _FinancialPulse({
    required this.total,
    required this.sales,
    required this.debt,
    required this.debtOperations,
  });

  final String total;
  final String sales;
  final String debt;
  final String debtOperations;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final colors = Theme.of(context).colorScheme;
    final foreground = colors.onPrimary;

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.primary,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: colors.primary.withValues(alpha: 0.20),
            blurRadius: 26,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: foreground.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(13),
                ),
                child: Icon(
                  Icons.account_balance_wallet_outlined,
                  color: foreground,
                  size: 21,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  l10n.homeCashReceived,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: foreground.withValues(alpha: 0.90),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            total,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              color: foreground,
              fontSize: 29,
              fontWeight: FontWeight.w900,
              letterSpacing: -0.4,
            ),
          ),
          const SizedBox(height: 15),
          Container(height: 1, color: foreground.withValues(alpha: 0.14)),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _MoneyMetric(
                  label: l10n.homeCashSales,
                  amount: sales,
                  foreground: foreground,
                ),
              ),
              const SizedBox(width: 18),
              Expanded(
                child: _MoneyMetric(
                  label: l10n.homeDebtCollections,
                  amount: debt,
                  detail: l10n.homeDebtOperations(debtOperations),
                  foreground: foreground,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MoneyMetric extends StatelessWidget {
  const _MoneyMetric({
    required this.label,
    required this.amount,
    required this.foreground,
    this.detail,
  });

  final String label;
  final String amount;
  final String? detail;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: foreground.withValues(alpha: 0.72),
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 3),
        Text(
          amount,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
            color: foreground,
            fontWeight: FontWeight.w800,
          ),
        ),
        if (detail != null) ...[
          const SizedBox(height: 2),
          Text(
            detail!,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: foreground.withValues(alpha: 0.64),
            ),
          ),
        ],
      ],
    );
  }
}
