import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/application/custody_coordinator.dart';
import 'package:wanasah_frontend/features/custody/data/custody_client.dart';
import 'package:wanasah_frontend/features/custody/data/pending_transfer_source.dart';
import 'package:wanasah_frontend/features/custody/data/transfer_response_gateway.dart';
import 'package:wanasah_frontend/features/custody/domain/stock_disclosure.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';
import 'package:wanasah_frontend/models/product_model.dart';

Map<String, dynamic> _product({Object? cartons = 0, Object? packs = 0}) => {
  'id': 17,
  'name': 'Physical stock',
  'packs_per_carton': 8,
  'current_cartons': cartons,
  'current_packs': packs,
};

Map<String, dynamic> _custodyItem(int id) => {
  'product_variant_id': id,
  'product_name': 'Variant $id',
  'stock_status': 'DAMAGED',
  'uom_code': 'EACH',
  'quantity': '1.000',
};

CustodyCoordinator _coordinator(CustodyClient client) => CustodyCoordinator(
  custodyClient: client,
  pendingTransfers: PendingTransferSource(
    remoteFetch: () async => [],
    localFetch: () async => <Map<String, dynamic>>[],
  ),
  transferGateway: CustodyTransferGateway(),
);

Widget _stockWidget(Locale locale, StockDisclosure disclosure, {
  List<ProductModel> products = const [],
}) => MaterialApp(
  locale: locale,
  supportedLocales: AppLocalizations.supportedLocales,
  localizationsDelegates: AppLocalizations.localizationsDelegates,
  home: Scaffold(
    body: SingleChildScrollView(
      child: VehicleInventorySection(
        products: products,
        sellableDisclosure: disclosure,
        nonSellableCustody: const [],
        nonSellableDisclosure: StockDisclosure.verified,
      ),
    ),
  ),
);

void main() {
  test('zero is valid but omitted/null/malformed/negative custody never becomes zero', () {
    final zero = ProductModel.fromJson(_product());
    expect(zero.currentCartons, 0);
    expect(zero.currentPacks, 0);
    expect(ProductModel.fromJson(_product(cartons: 2, packs: 3)).currentPacks, 3);
    for (final value in [null, 'unavailable', -1, 1.5]) {
      expect(() => ProductModel.fromJson(_product(cartons: value)),
          throwsFormatException, reason: 'cartons=$value');
      expect(() => ProductModel.fromJson(_product(packs: value)),
          throwsFormatException, reason: 'packs=$value');
    }
    final missingCartons = _product()..remove('current_cartons');
    final missingPacks = _product()..remove('current_packs');
    expect(() => ProductModel.fromJson(missingCartons), throwsFormatException);
    expect(() => ProductModel.fromJson(missingPacks), throwsFormatException);
    expect(ProductModel.fromJson({
      'id': 17, 'remaining_cartons': 0, 'remaining_packs': 0,
    }).currentCartons, 0);
  });

  test('101 custody records require cursor and keep exact session', () async {
    final calls = <Map<String, dynamic>>[];
    final items = await _coordinator(CustodyClient(get: (path, {queryParameters}) async {
      expect(path, '/driver/custody');
      calls.add(Map<String, dynamic>.from(queryParameters!));
      if (queryParameters['cursor'] == null) {
        return {
          'session_id': 42,
          'items': List.generate(100, (i) => _custodyItem(i + 1)),
          'next_cursor': 'opaque-session-cursor',
        };
      }
      expect(queryParameters['cursor'], 'opaque-session-cursor');
      return {
        'session_id': 42,
        'items': [_custodyItem(101)],
        'next_cursor': null,
      };
    })).loadNonSellableCustody();
    expect(items.length, 101);
    expect(items.first.productVariantId, 1);
    expect(items.last.productVariantId, 101);
    expect(calls, [
      {'limit': 100}, {'limit': 100, 'cursor': 'opaque-session-cursor'},
    ]);
    expect(() => items.removeLast(), throwsUnsupportedError);
  });

  test('cross-session page and repeated cursor fail closed', () async {
    for (final mode in ['session', 'cursor']) {
      final client = CustodyClient(get: (_, {queryParameters}) async => {
        'session_id': queryParameters?['cursor'] == null ? 7 : (mode == 'session' ? 8 : 7),
        'items': [_custodyItem(1)],
        'next_cursor': 'same-cursor',
      });
      await expectLater(_coordinator(client).loadNonSellableCustody(),
          throwsFormatException);
    }
  });

  test('denied second page cannot return incomplete first page', () async {
    var pages = 0;
    final client = CustodyClient(get: (path, {queryParameters}) async {
      pages++;
      if (pages == 1) {
        return {
          'session_id': 11,
          'items': List.generate(100, (i) => _custodyItem(i + 1)),
          'next_cursor': 'cursor-page-2',
        };
      }
      final request = RequestOptions(path: path);
      throw DioException(
        requestOptions: request,
        response: Response(requestOptions: request, statusCode: 403),
        type: DioExceptionType.badResponse,
      );
    });
    await expectLater(_coordinator(client).loadNonSellableCustody(), throwsException);
    expect(pages, 2);
  });

  for (final locale in const [Locale('ar'), Locale('en')]) {
    testWidgets('verified zero and AR/EN stock labels: ${locale.languageCode}', (tester) async {
      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.verified));
      expect(find.text(locale.languageCode == 'ar'
          ? 'لا يوجد مخزون متاح للبيع في السيارة حالياً.'
          : 'No sellable stock is currently in the vehicle.'), findsOneWidget);
      expect(find.textContaining('balance is unknown'), findsNothing);

      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.verified,
        products: [ProductModel.fromJson(_product())]));
      expect(find.text('Physical stock'), findsOneWidget);
      expect(find.textContaining(locale.languageCode == 'ar' ? 'المتبقي: 0' : 'Remaining: 0'), findsOneWidget);
    });

    testWidgets('denial hides quantities; transient stale is explicit: ${locale.languageCode}', (tester) async {
      final product = ProductModel.fromJson(_product(cartons: 4, packs: 1));
      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.denied,
        products: [product]));
      expect(find.text('Physical stock'), findsNothing);
      expect(find.text(locale.languageCode == 'ar'
          ? 'لا توجد صلاحية لعرض العهدة الحالية.'
          : 'You do not have access to current custody.'), findsOneWidget);

      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.stale,
        products: [product]));
      expect(find.text('Physical stock'), findsOneWidget);
      expect(find.text(locale.languageCode == 'ar'
          ? 'مخزون محفوظ للاستخدام دون اتصال؛ ليس رصيداً حالياً مؤكداً.'
          : 'Saved offline stock; not a verified current balance.'), findsOneWidget);
    });
  }
}
