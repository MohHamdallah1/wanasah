class ShopCreateCommand {
  const ShopCreateCommand({
    required this.requestId,
    required this.name,
    required this.phoneNumber,
    this.address,
    this.contactPerson,
    this.notes,
    this.locationLink,
    this.latitude,
    this.longitude,
  });

  final String requestId;
  final String name;
  final String phoneNumber;
  final String? address;
  final String? contactPerson;
  final String? notes;
  final String? locationLink;
  final double? latitude;
  final double? longitude;

  Map<String, dynamic> toJson() => {
        'request_id': requestId,
        'name': name,
        'phone_number': phoneNumber,
        if (address != null && address!.isNotEmpty) 'address': address,
        if (contactPerson != null && contactPerson!.isNotEmpty)
          'contact_person': contactPerson,
        if (notes != null && notes!.isNotEmpty) 'notes': notes,
        if (locationLink != null && locationLink!.isNotEmpty)
          'location_link': locationLink,
        if (latitude != null) 'latitude': latitude,
        if (longitude != null) 'longitude': longitude,
      };
}

class ShopCommercialReadiness {
  const ShopCommercialReadiness({
    required this.status,
    required this.saleReady,
    required this.code,
    required this.requiredAction,
  });

  final String status;
  final bool saleReady;
  final String? code;
  final String? requiredAction;

  factory ShopCommercialReadiness.fromJson(Map<String, dynamic> json) {
    return ShopCommercialReadiness(
      status: json['status']?.toString() ?? '',
      saleReady: json['sale_ready'] == true,
      code: json['code']?.toString(),
      requiredAction: json['required_action']?.toString(),
    );
  }
}

class ShopCreateResult {
  const ShopCreateResult({
    required this.shopId,
    required this.shopName,
    required this.commercialReadiness,
  });

  final int shopId;
  final String shopName;
  final ShopCommercialReadiness commercialReadiness;
}

class ShopCreateFailure implements Exception {
  const ShopCreateFailure({
    required this.ambiguous,
    required this.status,
    required this.code,
    required this.context,
    required this.requestId,
    required this.displayFallback,
  });

  final bool ambiguous;
  final int? status;
  final String? code;
  final Map<String, dynamic> context;
  final String? requestId;
  final String? displayFallback;
}

abstract class ShopCreationGateway {
  Future<ShopCreateResult> create(ShopCreateCommand command);
}
