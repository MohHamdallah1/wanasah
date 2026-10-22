import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/domain/commercial/commercial_readiness.dart';

void main() {
  test('canonical READY tax setup parses without a Flutter jurisdiction choice', () {
    final state = CommercialReadiness.fromResponse({
      'commercial_readiness': {
        'status': 'READY', 'sale_ready': true, 'code': null, 'required_action': null,
      },
    });
    expect(state.status, CommercialReadinessStatus.ready);
    expect(state.saleReady, isTrue);
    expect(state.code, isNull);
    expect(state.requiredAction, isNull);
  });

  for (final code in [
    'SHOP_TAX_JURISDICTION_REQUIRED', 'SHOP_TAX_JURISDICTION_REVIEW_REQUIRED',
  ]) {
    test('actionable tax completion preserves code $code', () {
      final state = CommercialReadiness.fromResponse({
        'shop': {'id': 99},
        'commercial_readiness': {
          'status': 'ACTION_REQUIRED', 'sale_ready': false, 'code': code,
          'required_action': 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
        },
      });
      expect(state.saleReady, isFalse);
      expect(state.status, CommercialReadinessStatus.actionRequired);
      expect(state.code, code);
      expect(state.requiredAction, 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION');
    });
  }

  test('contradictory or unknown readiness never becomes a ready sale', () {
    for (final json in [
      {'status': 'READY', 'sale_ready': false},
      {'status': 'ACTION_REQUIRED', 'sale_ready': true, 'code': 'X', 'required_action': 'Y'},
      {'status': 'READY', 'sale_ready': true, 'required_action': 'Y'},
      {'status': 'UNKNOWN', 'sale_ready': true},
      {'status': 'ACTION_REQUIRED', 'sale_ready': false, 'code': 'X'},
    ]) {
      expect(() => CommercialReadiness.fromJson(json), throwsFormatException);
    }
  });

}
