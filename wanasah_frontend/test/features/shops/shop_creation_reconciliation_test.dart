import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/shops/application/shop_creation_service.dart';
import 'package:wanasah_frontend/features/shops/domain/shop_creation.dart';

class _FakeGateway implements ShopCreationGateway {
  _FakeGateway(this.responses);

  final List<Object> responses;
  final List<ShopCreateCommand> calls = [];

  @override
  Future<ShopCreateResult> create(ShopCreateCommand command) async {
    calls.add(command);
    final next = responses.removeAt(0);
    if (next is ShopCreateResult) return next;
    throw next;
  }
}

void main() {
  test('ambiguous shop creation replays exact same command identity', () async {
    const ambiguous = ShopCreateFailure(
      ambiguous: true,
      status: null,
      code: null,
      context: <String, dynamic>{},
      requestId: null,
      displayFallback: 'network',
    );
    const success = ShopCreateResult(
      shopId: 9,
      shopName: 'Shop',
      commercialReadiness: ShopCommercialReadiness(
        status: 'ACTION_REQUIRED',
        saleReady: false,
        code: 'SHOP_TAX_JURISDICTION_REQUIRED',
        requiredAction: 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
      ),
    );

    final gateway = _FakeGateway(<Object>[ambiguous, success]);
    final service = ShopCreationService(client: gateway);
    const command = ShopCreateCommand(
      requestId: '11111111-1111-4111-8111-111111111111',
      name: 'Shop',
      phoneNumber: '0790000000',
      latitude: 31.95,
      longitude: 35.91,
    );

    final result = await service.execute(command);

    expect(result.shopId, 9);
    expect(gateway.calls, hasLength(2));
    expect(gateway.calls[0].requestId, command.requestId);
    expect(gateway.calls[1].requestId, command.requestId);
    expect(gateway.calls[0].toJson(), gateway.calls[1].toJson());
  });

  test('commercial readiness remains explicit and not inferred locally', () {
    final readiness = ShopCommercialReadiness.fromJson(
      <String, dynamic>{
        'status': 'ACTION_REQUIRED',
        'sale_ready': false,
        'code': 'SHOP_TAX_JURISDICTION_REQUIRED',
        'required_action': 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
      },
    );

    expect(readiness.saleReady, isFalse);
    expect(readiness.code, 'SHOP_TAX_JURISDICTION_REQUIRED');
    expect(
      readiness.requiredAction,
      'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
    );
  });

  test('AddShopScreen delegates transport to feature-owned service', () async {
    final source = await File('lib/screens/add_shop_screen.dart').readAsString();

    expect(source, contains('ShopCreationService'));
    expect(source, contains('_pendingShopCommand ??='));
    expect(source, isNot(contains('ApiClient.instance.post')));
    expect(source, isNot(contains("'/shops'")));
  });
}
