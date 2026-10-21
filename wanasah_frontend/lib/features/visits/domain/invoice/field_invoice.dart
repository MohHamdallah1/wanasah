import 'package:wanasah_frontend/core/serialization/json_contract.dart';

enum FieldInvoiceStatus {
  preview('PREVIEW'),
  committed('COMMITTED');

  const FieldInvoiceStatus(this.code);
  final String code;
}

enum InvoiceRoundingMode {
  halfUp('HALF_UP'),
  halfEven('HALF_EVEN');

  const InvoiceRoundingMode(this.code);
  final String code;
}

class InvoiceRounding {
  const InvoiceRounding._(this.precision, this.mode);
  final int precision;
  final InvoiceRoundingMode mode;

  factory InvoiceRounding.fromJson(Object? value) {
    final json = JsonContract.object(value, 'invoice.rounding');
    final precision = JsonContract.integer(json['precision'], 'rounding.precision');
    if (precision > 6) JsonContract.invalid('rounding.precision');
    return InvoiceRounding._(
      precision,
      JsonContract.code(json['mode'], InvoiceRoundingMode.values,
        (mode) => mode.code, 'rounding.mode'),
    );
  }
}

/// Exact Backend amounts. No arithmetic, float conversion or client repricing.
class InvoiceTotals {
  const InvoiceTotals._({
    required this.grossAmount,
    required this.discountAmount,
    required this.postOfferAmount,
    required this.taxableAmount,
    required this.taxAmount,
    required this.lineTotalAmount,
    required this.roundingAdjustment,
    required this.finalAmount,
  });

  final String grossAmount;
  final String discountAmount;
  final String postOfferAmount;
  final String taxableAmount;
  final String taxAmount;
  final String lineTotalAmount;
  final String roundingAdjustment;
  final String finalAmount;

  factory InvoiceTotals.fromJson(Object? value) {
    final json = JsonContract.object(value, 'invoice.totals');
    String amount(String key) => JsonContract.decimal(json[key], 'totals.$key');
    return InvoiceTotals._(
      grossAmount: amount('gross_amount'),
      discountAmount: amount('discount_amount'),
      postOfferAmount: amount('post_offer_amount'),
      taxableAmount: amount('taxable_amount'),
      taxAmount: amount('tax_amount'),
      lineTotalAmount: amount('line_total_amount'),
      roundingAdjustment: amount('rounding_adjustment'),
      finalAmount: amount('final_amount'),
    );
  }
}

class FieldInvoiceLine {
  const FieldInvoiceLine._({
    required this.productVariantId,
    required this.grossAmount,
    required this.discountAmount,
    required this.taxAmount,
    required this.finalAmount,
  });

  final int productVariantId;
  final String grossAmount;
  final String discountAmount;
  final String taxAmount;
  final String finalAmount;

  factory FieldInvoiceLine.fromJson(Object? value) {
    final json = JsonContract.object(value, 'invoice.line');
    return FieldInvoiceLine._(
      productVariantId: JsonContract.integer(
        json['product_variant_id'], 'line.product_variant_id', minimum: 1),
      grossAmount: JsonContract.decimal(json['gross_amount'], 'line.gross_amount'),
      discountAmount: JsonContract.decimal(json['discount_amount'], 'line.discount_amount'),
      taxAmount: JsonContract.decimal(json['tax_amount'], 'line.tax_amount'),
      finalAmount: JsonContract.decimal(json['final_amount'], 'line.final_amount'),
    );
  }
}

class FieldInvoiceReward {
  const FieldInvoiceReward._(this.productVariantId, this.baseQuantity);
  final int productVariantId;
  final String baseQuantity;

  factory FieldInvoiceReward.fromJson(Object? value) {
    final json = JsonContract.object(value, 'invoice.reward');
    return FieldInvoiceReward._(
      JsonContract.integer(json['product_variant_id'], 'reward.product_variant_id', minimum: 1),
      JsonContract.decimal(json['base_quantity'], 'reward.base_quantity'),
    );
  }
}

class FieldInvoice {
  FieldInvoice._({
    required this.status,
    required this.currencyCode,
    required this.calculatedAt,
    required this.rounding,
    required this.totals,
    required List<FieldInvoiceLine> lines,
    required List<FieldInvoiceReward> rewards,
    required this.revisionNumber,
  }) : lines = List.unmodifiable(lines), rewards = List.unmodifiable(rewards);

  final FieldInvoiceStatus status;
  final String currencyCode;
  /// Original ISO timestamp; presentation chooses the locale/timezone.
  final String calculatedAt;
  final InvoiceRounding rounding;
  final InvoiceTotals totals;
  final List<FieldInvoiceLine> lines;
  final List<FieldInvoiceReward> rewards;
  /// Supplied by the frozen read; immediate mutation results may omit it.
  final int? revisionNumber;

  factory FieldInvoice.fromJson(Object? value) {
    final json = JsonContract.object(value, 'invoice');
    final timestamp = JsonContract.text(json['calculated_at'], 'calculated_at');
    if (DateTime.tryParse(timestamp) == null) JsonContract.invalid('calculated_at');
    final lines = JsonContract.list(json['lines'], 'invoice.lines');
    final rewards = JsonContract.list(json['rewards'], 'invoice.rewards');
    if (lines.length > 500 || rewards.length > 500) {
      JsonContract.invalid('invoice.lines');
    }
    return FieldInvoice._(
      status: JsonContract.code(json['status'], FieldInvoiceStatus.values,
        (status) => status.code, 'invoice.status'),
      currencyCode: JsonContract.text(json['currency_code'], 'currency_code'),
      calculatedAt: timestamp,
      rounding: InvoiceRounding.fromJson(json['rounding']),
      totals: InvoiceTotals.fromJson(json['totals']),
      lines: lines.map(FieldInvoiceLine.fromJson).toList(),
      rewards: rewards.map(FieldInvoiceReward.fromJson).toList(),
      revisionNumber: json['revision_number'] == null ? null : JsonContract.integer(
        json['revision_number'], 'revision_number', minimum: 1),
    );
  }
}

class InvoicePreview {
  const InvoicePreview._(this.invoice);
  final FieldInvoice invoice;
  bool get commitRequired => true;

  factory InvoicePreview.fromJson(Object? value) {
    final json = JsonContract.object(value, 'invoice_preview');
    final invoice = FieldInvoice.fromJson(json['invoice']);
    if (json['commit_required'] != true || invoice.status != FieldInvoiceStatus.preview) {
      JsonContract.invalid('invoice_preview.status');
    }
    return InvoicePreview._(invoice);
  }
}

/// Missing old replay evidence is different from explicit non-sale evidence.
enum InvoiceAvailability { legacyResponse, none, available }

class CommittedInvoiceResult {
  const CommittedInvoiceResult._(this.availability, this.invoice);
  final InvoiceAvailability availability;
  final FieldInvoice? invoice;

  factory CommittedInvoiceResult.fromVisitResult(Object? value) =>
      CommittedInvoiceResult._parse(value, frozenRead: false);

  factory CommittedInvoiceResult.fromReadResponse(Object? value) =>
      CommittedInvoiceResult._parse(value, frozenRead: true);

  static CommittedInvoiceResult _parse(Object? value, {required bool frozenRead}) {
    final json = JsonContract.object(value, 'invoice_result');
    if (!json.containsKey('invoice')) {
      if (frozenRead) JsonContract.invalid('invoice_result.invoice');
      return const CommittedInvoiceResult._(InvoiceAvailability.legacyResponse, null);
    }
    if (json['invoice'] == null) {
      return const CommittedInvoiceResult._(InvoiceAvailability.none, null);
    }
    final invoice = FieldInvoice.fromJson(json['invoice']);
    if (invoice.status != FieldInvoiceStatus.committed ||
        (frozenRead && invoice.revisionNumber == null)) {
      JsonContract.invalid('invoice_result.status');
    }
    return CommittedInvoiceResult._(InvoiceAvailability.available, invoice);
  }
}
