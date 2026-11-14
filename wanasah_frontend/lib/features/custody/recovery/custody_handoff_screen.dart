import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'custody_handoff_client.dart';
import 'custody_handoff_quantity.dart';
import 'custody_handoff_strings.dart';

/// Real FIELD-only signed receipt, reachable from the existing Custody tab.
/// Sensitive offers and proofs stay in this route's in-memory controllers only.
/// Never enqueues offline commands or uses the manager's Backoffice session.
class CustodyHandoffScreen extends StatefulWidget {
  const CustodyHandoffScreen({super.key, this.client});
  final CustodyHandoffClient? client;

  @override
  State<CustodyHandoffScreen> createState() => _CustodyHandoffScreenState();
}

class _CustodyHandoffScreenState extends State<CustodyHandoffScreen> {
  final _offer = TextEditingController();
  CustodyHandoffPreview? _review;
  String? _reviewedOffer;
  String? _proof;
  String? _problem;
  bool _counted = false;
  bool _busy = false;

  late final CustodyHandoffClient _client =
      widget.client ?? CustodyHandoffClient();

  @override
  void dispose() {
    _offer.dispose(); // no offer/receipt in local SQLite or auth storage
    super.dispose();
  }

  void _onOfferChanged() {
    // Text changes must rebuild the inspect button even before the first read.
    setState(() {
      _review = null;
      _reviewedOffer = null;
      _proof = null;
      _counted = false;
      _problem = null;
    });
  }

  String _failure(Object error, CustodyHandoffStrings t) {
    if (error is DioException) {
      final body = error.response?.data;
      final envelope = body is Map ? body['error'] : null;
      final code = envelope is Map ? envelope['code']?.toString() : null;
      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        return t.t('denied');
      }
      if (code != null &&
          (code.contains('STALE') || code.contains('REVISION'))) {
        return t.t('stale');
      }
      if (code != null &&
          (code.contains('EXPIRED') || code.contains('PROOF_INVALID'))) {
        return t.t('expired');
      }
    }
    return t.t('unavailable');
  }

  Future<void> _inspect(CustodyHandoffStrings t) async {
    if (_busy || _offer.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _problem = null;
      _review = null;
      _proof = null;
      _counted = false;
    });
    final offered = _offer.text.trim();
    try {
      final verified = await _client.review(offered);
      if (!mounted || _offer.text.trim() != offered) return;
      setState(() {
        _review = verified;
        _reviewedOffer = offered;
        _proof = null;
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          _problem = _failure(error, t);
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  Future<void> _confirm(CustodyHandoffStrings t) async {
    final review = _review, offered = _reviewedOffer;
    if (_busy ||
        review == null ||
        offered == null ||
        !_counted ||
        _offer.text.trim() != offered) {
      return;
    }
    setState(() {
      _busy = true;
      _problem = null;
    });
    try {
      final proof = await _client.confirm(offered, review);
      if (!mounted || _offer.text.trim() != offered) return;
      setState(() {
        _proof = proof;
        _review = null;
        _counted = false;
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          _problem = _failure(error, t);
          _counted = false;
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  Future<void> _paste() async {
    if (_busy) return;
    final text = await Clipboard.getData(Clipboard.kTextPlain);
    if (!mounted || text?.text == null) return;
    _offer.text = text!.text!;
    _onOfferChanged();
  }

  Future<void> _copyReceipt(CustodyHandoffStrings t) async {
    final signed = _proof;
    if (signed == null) return;
    await Clipboard.setData(ClipboardData(text: signed));
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(t.t('copied'))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = CustodyHandoffStrings.of(context);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(t.t('title'))),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              t.t('instruction'),
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _offer,
              onChanged: (_) => _onOfferChanged(),
              enabled: !_busy && _proof == null,
              maxLines: 3,
              maxLength: 2048,
              autocorrect: false,
              enableSuggestions: false,
              keyboardType: TextInputType.multiline,
              decoration: InputDecoration(
                labelText: t.t('paste'),
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  tooltip: t.t('pasteButton'),
                  onPressed: _busy ? null : _paste,
                  icon: const Icon(Icons.content_paste),
                ),
              ),
            ),
            const SizedBox(height: 8),
            if (_proof == null)
              FilledButton.icon(
                key: const ValueKey('c03-inspect-stock'),
                onPressed:
                    _busy || _offer.text.trim().isEmpty
                        ? null
                        : () => _inspect(t),
                icon: const Icon(Icons.fact_check_outlined),
                label: Text(t.t('inspect')),
              ),
            if (_busy)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (_problem != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Text(_problem!, style: TextStyle(color: scheme.error)),
              ),
            if (_review != null) ...[
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        '${t.t("vehicle")}: ${_review!.vehiclePlate}',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 8),
                      if (_review!.rows.isEmpty) Text(t.t('empty')),
                      for (final item in _review!.rows) ...[
                        Text(
                          (item['product_name'] ?? '').toString(),
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        Text(
                          '${(item["batch_number"] ?? "").toString().isEmpty ? t.t("noLot") : "${t.t("batch")}: ${item["batch_number"]}"}'
                          '${item["expiry_date"] == null ? "" : " · ${t.t("expiry")}: ${item["expiry_date"]}"}',
                        ),
                        Text(
                          '${t.t("quantity")}: ${formatCustodyHandoffQuantity(item, locale: Localizations.localeOf(context).languageCode)}',
                        ),
                        Text(
                          '${t.t("status")}: ${t.status((item["stock_status"] ?? "").toString())}',
                        ),
                        if ((item['reserved_base'] ?? '0').toString() != '0')
                          Text('${t.t("reserved")}: ${item["reserved_base"]}'),
                        const Divider(height: 24),
                      ],
                    ],
                  ),
                ),
              ),
              CheckboxListTile(
                key: const ValueKey('c03-count-confirmation'),
                value: _counted,
                title: Text(t.t('count')),
                controlAffinity: ListTileControlAffinity.leading,
                contentPadding: EdgeInsets.zero,
                onChanged:
                    _busy
                        ? null
                        : (value) => setState(() {
                          _counted = value == true;
                        }),
              ),
              FilledButton(
                key: const ValueKey('c03-field-sign'),
                onPressed: _busy || !_counted ? null : () => _confirm(t),
                child: Text(t.t('submit')),
              ),
            ],
            if (_proof != null) ...[
              const SizedBox(height: 14),
              Text(
                t.t('receipt'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 10),
              FilledButton.icon(
                key: const ValueKey('c03-copy-proof'),
                onPressed: _busy ? null : () => _copyReceipt(t),
                icon: const Icon(Icons.copy_all),
                label: Text(t.t('copyProof')),
              ),
            ],
            const SizedBox(height: 16),
            Text(t.t('secure'), style: Theme.of(context).textTheme.bodySmall),
            Text(t.t('offline'), style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
