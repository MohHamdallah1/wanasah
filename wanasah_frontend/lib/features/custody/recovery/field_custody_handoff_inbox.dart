import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import 'custody_handoff_grouping.dart';
import 'custody_handoff_quantity.dart';
import 'custody_handoff_strings.dart';
import 'field_custody_handoff_client.dart';

String _message(BuildContext context, Object error) {
  final t = CustodyHandoffStrings.of(context);
  if (error is DioException) {
    final status = error.response?.statusCode, body = error.response?.data;
    final details = body is Map ? body['error'] : null;
    final code = details is Map ? (details['code'] ?? '').toString() : '';
    if (status == 401 || status == 403 || code.contains('REVOKED')) {
      return t.t('denied');
    }
    if (code.contains('EXPIRED')) return t.t('expiredState');
    if (status == 409 || code.contains('STALE') || code.contains('REVISION')) {
      return t.t('stale');
    }
  }
  return t.t('inboxFail');
}

String _stateLabel(CustodyHandoffStrings t, String state) => switch (state) {
  'PENDING' => t.t('waiting'),
  'CONFIRMED' => t.t('confirmedState'),
  'DECLINED' => t.t('declinedState'),
  'CANCELLED' => t.t('cancelledState'),
  'EXPIRED' => t.t('expiredState'),
  'COMMITTED' => t.t('committedState'),
  _ => t.t('inboxFail'),
};

/// Embedded in the actual FIELD custody tab. One own-principal read on entry;
/// refetch only on explicit refresh/return, never a background worker.
class FieldCustodyHandoffInbox extends StatefulWidget {
  const FieldCustodyHandoffInbox({
    super.key,
    this.client,
    this.refreshNonce = 0,
  });
  final FieldCustodyHandoffClient? client;
  final int refreshNonce;
  @override
  State<FieldCustodyHandoffInbox> createState() =>
      _FieldCustodyHandoffInboxState();
}

class _FieldCustodyHandoffInboxState extends State<FieldCustodyHandoffInbox> {
  late final FieldCustodyHandoffClient _client =
      widget.client ?? FieldCustodyHandoffClient();
  List<FieldCustodyRequest> _items = const [];
  bool _loading = true;
  String? _problem;
  int _generation = 0;
  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(covariant FieldCustodyHandoffInbox oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshNonce != widget.refreshNonce) _reload();
  }

  void _reload() {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _problem = null;
    });
    _client
        .pending()
        .then((items) {
          if (!mounted || generation != _generation) return;
          setState(() {
            _items = items;
            _loading = false;
          });
        })
        .catchError((Object error) {
          if (!mounted || generation != _generation) return;
          // Never display stale prior-principal inbox after an authorization failure.
          setState(() {
            _items = const [];
            _loading = false;
            _problem = _message(context, error);
          });
        });
  }

  @override
  void dispose() {
    _generation++;
    super.dispose();
  }

  Future<void> _open(FieldCustodyRequest item) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder:
            (_) => FieldCustodyHandoffRequestScreen(
              handoffId: item.handoffId,
              client: _client,
            ),
      ),
    );
    if (mounted) _reload();
  }

  @override
  Widget build(BuildContext context) {
    final t = CustodyHandoffStrings.of(context);
    return Card(
      key: const ValueKey('field-custody-inbox'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    t.t('inbox'),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  key: const ValueKey('field-custody-inbox-refresh'),
                  tooltip: t.t('inboxRefresh'),
                  icon: const Icon(Icons.refresh),
                  onPressed: _loading ? null : _reload,
                ),
              ],
            ),
            if (_loading) const LinearProgressIndicator(),
            if (_problem != null)
              Text(
                _problem!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (!_loading && _problem == null && _items.isEmpty)
              Text(t.t('inboxEmpty')),
            for (final item in _items)
              ListTile(
                key: ValueKey('field-custody-inbox-${item.handoffId}'),
                contentPadding: EdgeInsets.zero,
                title: Text(item.vehiclePlate),
                subtitle: Text(_stateLabel(t, item.state)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(item),
              ),
          ],
        ),
      ),
    );
  }
}

/// Signed own-principal review; no proof or stock moves are ever generated here.
class FieldCustodyHandoffRequestScreen extends StatefulWidget {
  const FieldCustodyHandoffRequestScreen({
    super.key,
    required this.handoffId,
    required this.client,
  });
  final String handoffId;
  final FieldCustodyHandoffClient client;
  @override
  State<FieldCustodyHandoffRequestScreen> createState() =>
      _FieldCustodyHandoffRequestScreenState();
}

class _FieldCustodyHandoffRequestScreenState
    extends State<FieldCustodyHandoffRequestScreen> {
  final _notes = TextEditingController();
  FieldCustodyRequest? _request;
  bool _loading = true, _busy = false, _counted = false;
  String? _problem, _reason;
  String? _decisionId, _decisionKind;
  String? _decisionSnapshot, _decisionReason, _decisionReasonText;
  int _generation = 0;
  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _generation++;
    _notes.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _problem = null;
      _counted = false;
    });
    try {
      final verified = await widget.client.detail(widget.handoffId);
      if (!mounted || generation != _generation) return;
      setState(() {
        _request = verified;
        _loading = false;
        // An uncertain POST may still be in flight at the server.
        // When the authoritative state remains PENDING, keep its original ID/body.
        if (verified.state != 'PENDING') {
          _decisionId = null;
          _decisionKind = null;
          _decisionSnapshot = null;
          _decisionReason = null;
          _decisionReasonText = null;
        }
      });
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() {
        _request = null;
        _loading = false;
        _problem = _message(context, error);
      });
    }
  }

  Future<void> _decide(String decision) async {
    final request = _request;
    if (request == null || request.state != 'PENDING' || _busy || _loading) {
      return;
    }
    if (decision == 'CONFIRM' && !_counted) return;
    if (decision == 'DECLINE' && _reason == null) {
      setState(
        () => _problem = CustodyHandoffStrings.of(context).t('declineRequired'),
      );
      return;
    }
    // The same UUID is retained while a response is uncertain. A new action
    // cannot be chosen until a fresh authenticated GET verifies the state.
    final requestId = _decisionId ?? widget.client.newRequestId();
    if (_decisionKind != null && _decisionKind != decision) return;
    if (_decisionId != null &&
        (_decisionSnapshot != request.stockSnapshot ||
            _decisionReason != (decision == 'DECLINE' ? _reason : null) ||
            _decisionReasonText !=
                (decision == 'DECLINE' ? _notes.text.trim() : null))) {
      setState(() => _problem = CustodyHandoffStrings.of(context).t('stale'));
      return;
    }
    _decisionId = requestId;
    _decisionKind = decision;
    _decisionSnapshot = request.stockSnapshot;
    _decisionReason = decision == 'DECLINE' ? _reason : null;
    _decisionReasonText = decision == 'DECLINE' ? _notes.text.trim() : null;
    setState(() {
      _busy = true;
      _problem = null;
    });
    try {
      final verified = await widget.client.decide(
        request: request,
        requestId: requestId,
        decision: decision,
        physicalCountConfirmed: decision == 'CONFIRM' && _counted,
        reasonCode: decision == 'DECLINE' ? _reason : null,
        reasonText: decision == 'DECLINE' ? _notes.text.trim() : null,
      );
      if (!mounted) return;
      setState(() {
        _request = verified;
        _counted = false;
        _decisionId = null;
        _decisionKind = null;
        _decisionSnapshot = null;
        _decisionReason = null;
        _decisionReasonText = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _counted = false;
        _problem =
            '${_message(context, error)} ${CustodyHandoffStrings.of(context).t('decisionFail')}';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = CustodyHandoffStrings.of(context), request = _request;
    final lines =
        request == null
            ? const <Map<String, dynamic>>[]
            : visibleCustodyHandoffLines(request.stockLines);
    final locale = Localizations.localeOf(context).languageCode;
    return Scaffold(
      appBar: AppBar(title: Text(t.t('inboxOpen'))),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_loading) const LinearProgressIndicator(),
            if (_problem != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  _problem!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (request != null) ...[
              Text(
                '${t.t('vehicle')}: ${request.vehiclePlate}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(
                _stateLabel(t, request.state),
                key: const ValueKey('field-handoff-state'),
              ),
              if (DateTime.tryParse(request.expiresAt)
                  case final DateTime expires)
                Text(
                  '${t.t('requestDeadline')}: ${MaterialLocalizations.of(context).formatMediumDate(expires.toLocal())} ${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(expires.toLocal()))}',
                ),
              const SizedBox(height: 8),
              if (lines.isEmpty) Text(t.t('empty')),
              for (final line in lines)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          (line['product_name'] ?? '').toString(),
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        Text(
                          ((line['batch_number'] ?? '').toString().isEmpty)
                              ? t.t('noLot')
                              : '${t.t('batch')}: ${line['batch_number']}',
                        ),
                        if (line['expiry_date'] != null)
                          Text('${t.t('expiry')}: ${line['expiry_date']}'),
                        Text(
                          '${t.t('quantity')}: ${formatCustodyHandoffQuantity(line, locale: locale)}',
                        ),
                        Text(
                          '${t.t('status')}: ${t.status((line['stock_status'] ?? '').toString())}',
                        ),
                        if ((line['reserved_base'] ?? '0').toString() != '0')
                          Text(
                            '${t.t('reserved')}: ${formatCustodyHandoffQuantity({...line, 'on_hand_base': line['reserved_base']}, locale: locale)}',
                          ),
                      ],
                    ),
                  ),
                ),
              if (request.state == 'PENDING') ...[
                const SizedBox(height: 10),
                Text(t.t('instruction')),
                CheckboxListTile(
                  key: const ValueKey('field-handoff-count-checkbox'),
                  value: _counted,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(t.t('physicalCount')),
                  onChanged:
                      _busy
                          ? null
                          : (value) => setState(() => _counted = value == true),
                ),
                FilledButton(
                  key: const ValueKey('field-handoff-confirm'),
                  onPressed:
                      _busy ||
                              !_counted ||
                              (_decisionKind != null &&
                                  _decisionKind != 'CONFIRM')
                          ? null
                          : () => _decide('CONFIRM'),
                  child: Text(t.t('approveNew')),
                ),
                const Divider(height: 32),
                DropdownButtonFormField<String>(
                  key: const ValueKey('field-handoff-reason'),
                  value: _reason,
                  decoration: InputDecoration(
                    labelText: t.t('reason'),
                    border: const OutlineInputBorder(),
                  ),
                  items: [
                    DropdownMenuItem(
                      value: 'DISCREPANCY',
                      child: Text(t.t('discrepancy')),
                    ),
                    DropdownMenuItem(
                      value: 'NOT_MY_GOODS',
                      child: Text(t.t('notMine')),
                    ),
                    DropdownMenuItem(
                      value: 'VEHICLE_UNAVAILABLE',
                      child: Text(t.t('unavailableVehicle')),
                    ),
                    DropdownMenuItem(
                      value: 'OTHER',
                      child: Text(t.t('otherReason')),
                    ),
                  ],
                  onChanged:
                      _busy || _decisionId != null
                          ? null
                          : (value) => setState(() => _reason = value),
                ),
                const SizedBox(height: 8),
                TextField(
                  key: const ValueKey('field-handoff-reason-text'),
                  controller: _notes,
                  maxLength: 240,
                  maxLines: 2,
                  enabled: !_busy && _decisionId == null,
                  decoration: InputDecoration(
                    labelText: t.t('reasonDetails'),
                    border: const OutlineInputBorder(),
                  ),
                ),
                OutlinedButton(
                  key: const ValueKey('field-handoff-decline'),
                  onPressed:
                      _busy ||
                              _reason == null ||
                              (_decisionKind != null &&
                                  _decisionKind != 'DECLINE')
                          ? null
                          : () => _decide('DECLINE'),
                  child: Text(t.t('declineNew')),
                ),
              ],
            ],
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const ValueKey('field-handoff-refresh'),
              onPressed: _busy ? null : _refresh,
              icon: const Icon(Icons.refresh),
              label: Text(t.t('loadAgain')),
            ),
            Text(t.t('offline'), style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
