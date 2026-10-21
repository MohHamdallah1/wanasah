import 'package:uuid/uuid.dart';

import '../data/shop_creation_client.dart';
import '../domain/shop_creation.dart';

class ShopCreationService {
  ShopCreationService({
    ShopCreationClient? client,
    Uuid? uuid,
  })  : _client = client ?? ShopCreationClient(),
        _uuid = uuid ?? const Uuid();

  final ShopCreationClient _client;
  final Uuid _uuid;

  ShopCreateCommand prepare({
    required String name,
    required String phoneNumber,
    String? address,
    String? contactPerson,
    String? notes,
    String? locationLink,
    double? latitude,
    double? longitude,
  }) {
    return ShopCreateCommand(
      requestId: _uuid.v4(),
      name: name,
      phoneNumber: phoneNumber,
      address: address,
      contactPerson: contactPerson,
      notes: notes,
      locationLink: locationLink,
      latitude: latitude,
      longitude: longitude,
    );
  }

  Future<ShopCreateResult> execute(ShopCreateCommand command) async {
    try {
      return await _client.create(command);
    } on ShopCreateFailure catch (failure) {
      if (!failure.ambiguous) rethrow;
      // Operation-specific reconciliation: exact replay with the same UUID/body.
      return _client.create(command);
    }
  }
}
