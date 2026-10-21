import 'src/field_json.dart';

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
    final json = FieldJson.object(value, 'invoice.rounding');
    final precision = FieldJson.integer(json['precision'], 'rounding.precision');
    if (precision > 6) FieldJson.invalid('rounding.precision');
    return InvoiceRounding._(
      precision,
      FieldJson.code(json['mode'], InvoiceRoundingMode.values,
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
    final json = FieldJson.object(value, 'invoice.totals');
    String amount(String key) => FieldJson.decimal(json[key], 'totals.$key');
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
    final json = FieldJson.object(value, 'invoice.line');
    return FieldInvoiceLine._(
      productVariantId: FieldJson.integer(
        json['product_variant_id'], 'line.product_variant_id', minimum: 1),
      grossAmount: FieldJson.decimal(json['gross_amount'], 'line.gross_amount'),
      discountAmount: FieldJson.decimal(json['discount_amount'], 'line.discount_amount'),
      taxAmount: FieldJson.decimal(json['tax_amount'], 'line.tax_amount'),
      finalAmount: FieldJson.decimal(json['final_amount'], 'line.final_amount'),
    );
  }
}

class FieldInvoiceReward {
  const FieldInvoiceReward._(this.productVariantId, this.baseQuantity);
  final int productVariantId;
  final String baseQuantity;

  factory FieldInvoiceReward.fromJson(Object? value) {
    final json = FieldJson.object(value, 'invoice.reward');
    return FieldInvoiceReward._(
      FieldJson.integer(json['product_variant_id'], 'reward.product_variant_id', minimum: 1),
      FieldJson.decimal(json['base_quantity'], 'reward.base_quantity'),
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
    final json = FieldJson.object(value, 'invoice');
    final timestamp = FieldJson.text(json['calculated_at'], 'calculated_at');
    if (DateTime.tryParse(timestamp) == null) FieldJson.invalid('calculated_at');
    final lines = FieldJson.list(json['lines'], 'invoice.lines');
    final rewards = FieldJson.list(json['rewards'], 'invoice.rewards');
    if (lines.length > 500 || rewards.length > 500) {
      FieldJson.invalid('invoice.lines');
    }
    return FieldInvoice._(
      status: FieldJson.code(json['status'], FieldInvoiceStatus.values,
        (status) => status.code, 'invoice.status'),
      currencyCode: FieldJson.text(json['currency_code'], 'currency_code'),
      calculatedAt: timestamp,
      rounding: InvoiceRounding.fromJson(json['rounding']),
      totals: InvoiceTotals.fromJson(json['totals']),
      lines: lines.map(FieldInvoiceLine.fromJson).toList(),
      rewards: rewards.map(FieldInvoiceReward.fromJson).toList(),
      revisionNumber: json['revision_number'] == null ? null : FieldJson.integer(
        json['revision_number'], 'revision_number', minimum: 1),
    );
  }
}

class InvoicePreview {
  const InvoicePreview._(this.invoice);
  final FieldInvoice invoice;
  bool get commitRequired => true;

  factory InvoicePreview.fromJson(Object? value) {
    final json = FieldJson.object(value, 'invoice_preview');
    final invoice = FieldInvoice.fromJson(json['invoice']);
    if (json['commit_required'] != true || invoice.status != FieldInvoiceStatus.preview) {
      FieldJson.invalid('invoice_preview.status');
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
    final json = FieldJson.object(value, 'invoice_result');
    if (!json.containsKey('invoice')) {
      if (frozenRead) FieldJson.invalid('invoice_result.invoice');
      return const CommittedInvoiceResult._(InvoiceAvailability.legacyResponse, null);
    }
    if (json['invoice'] == null) {
      return const CommittedInvoiceResult._(InvoiceAvailability.none, null);
    }
    final invoice = FieldInvoice.fromJson(json['invoice']);
    if (invoice.status != FieldInvoiceStatus.committed ||
        (frozenRead && invoice.revisionNumber == null)) {
      FieldJson.invalid('invoice_result.status');
    }
    return CommittedInvoiceResult._(InvoiceAvailability.available, invoice);
  }
}
