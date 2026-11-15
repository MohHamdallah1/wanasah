import 'dart:developer' as developer;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../data/current_vehicle_stock_reader.dart';
import '../domain/vehicle_route_authority.dart';

/// Show live physical on-hand only when the CURRENT server route names a car.
///
/// No active route is a verified neutral state; a present route whose physical
/// custody fails to verify is an actual error. We never display SQLite stock.
class CurrentVehicleStockSection extends StatefulWidget {
  const CurrentVehicleStockSection({
    required this.route,
    this.refreshNonce = 0,
    this.reader,
    super.key,
  });

  final VehicleRouteAuthority route;
  final int refreshNonce;
  final CurrentVehicleStockReader? reader;

  @override
  State<CurrentVehicleStockSection> createState() =>
      _CurrentVehicleStockSectionState();
}

class _CurrentVehicleStockSectionState
    extends State<CurrentVehicleStockSection> {
  late CurrentVehicleStockReader _reader;
  CurrentVehicleStockSnapshot? _snapshot;
  Object? _error;
  bool _loading = false;
  int _requestEpoch = 0;

  @override
  void initState() {
    super.initState();
    _reader = widget.reader ?? CurrentVehicleStockReader();
    _beginRead();
  }

  @override
  void didUpdateWidget(covariant CurrentVehicleStockSection oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.route != widget.route ||
        oldWidget.refreshNonce != widget.refreshNonce ||
        oldWidget.reader != widget.reader) {
      _reader = widget.reader ?? CurrentVehicleStockReader();
      _beginRead();
    }
  }

  @override
  void dispose() {
    _requestEpoch++;
    super.dispose();
  }

  void _beginRead() {
    final epoch = ++_requestEpoch;
    _snapshot = null;
    _error = null;
    _loading = widget.route.kind == VehicleRouteKind.active;
    if (!_loading) return;

    // An older request for a different car or execution period cannot publish
    // its stock after a route/identity change or failed fresh verification.
    () async {
      try {
        final snapshot = await _reader.read(widget.route);
        if (!mounted || epoch != _requestEpoch) return;
        setState(() {
          _snapshot = snapshot;
          _loading = false;
        });
      } catch (error) {
        if (!mounted || epoch != _requestEpoch) return;
        final status =
            error is DioException
                ? (error.response?.statusCode?.toString() ?? 'offline')
                : 'invalid-contract';
        developer.log(
          '[FIELD physical stock] Signed vehicle read failed: type=${error.runtimeType}, status=$status',
        );
        setState(() {
          _error = error;
          _loading = false;
        });
      }
    }();
  }

  void _retry() => setState(_beginRead);

  String _statusLabel(String status, AppLocalizations l10n) => switch (status) {
    'DAMAGED' => l10n.stockStatusDamaged,
    'QUARANTINED' => l10n.stockStatusQuarantined,
    'BLOCKED' => l10n.stockStatusBlocked,
    'RECALLED' => l10n.stockStatusRecalled,
    'DISPOSAL_PENDING' => l10n.stockStatusDisposalPending,
    _ => status,
  };

  Widget _item(CurrentVehicleStockItem item, {String? statusLabel}) => Card(
    key: ValueKey('vehicle-physical-${item.productVariantId}-${item.status}'),
    margin: const EdgeInsets.only(bottom: 8),
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.name,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                if (statusLabel != null)
                  Text(statusLabel, style: const TextStyle(fontSize: 12)),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '${item.quantity} ${item.baseUomCode}',
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ],
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final isArabic = Localizations.localeOf(context).languageCode == 'ar';
    final route = widget.route;
    return Column(
      key: const ValueKey('field-current-physical-vehicle-stock'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          l10n.stockVehicleTitle,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        if (route.kind == VehicleRouteKind.noActiveRoute)
          Text(
            isArabic
                ? '\u0644\u0627 \u064a\u0648\u062c\u062f \u062e\u0637 \u0633\u064a\u0631 \u0623\u0648 \u062c\u0648\u0644\u0629 \u0645\u0641\u0639\u0651\u0644\u0629 \u062d\u0627\u0644\u064a\u064b\u0627.'
                : 'No active route or tour is currently assigned.',
            key: const ValueKey('field-no-active-route'),
          )
        else if (route.kind == VehicleRouteKind.unverified)
          Text(
            l10n.stockUnavailable,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          )
        else if (_loading)
          const Align(
            alignment: AlignmentDirectional.centerStart,
            child: Padding(
              padding: EdgeInsets.symmetric(vertical: 6),
              child: SizedBox(
                height: 18,
                width: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          )
        else if (_error != null) ...[
          Text(
            _error is DioException &&
                    ((_error as DioException).response?.statusCode == 401 ||
                        (_error as DioException).response?.statusCode == 403)
                ? l10n.stockDenied
                : l10n.stockUnavailable,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: TextButton.icon(
              onPressed: _retry,
              icon: const Icon(Icons.refresh_outlined),
              label: Text(l10n.retry),
            ),
          ),
        ] else if (_snapshot != null) ...[
          if (_snapshot!.sellable.isEmpty)
            Text(l10n.stockEmptyVerified)
          else
            ..._snapshot!.sellable.map(_item),
          if (_snapshot!.nonSellable.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              l10n.stockNonSellableTitle,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            ..._snapshot!.nonSellable.map(
              (item) =>
                  _item(item, statusLabel: _statusLabel(item.status, l10n)),
            ),
          ],
        ],
      ],
    );
  }
}
