import '../../../services/location_service.dart';

class WorkSessionCoordinates {
  const WorkSessionCoordinates({
    required this.latitude,
    required this.longitude,
  });

  final double latitude;
  final double longitude;

  bool get isContractValid =>
      latitude.isFinite &&
      longitude.isFinite &&
      latitude >= -90 &&
      latitude <= 90 &&
      longitude >= -180 &&
      longitude <= 180;
}

abstract interface class WorkSessionLocationSource {
  Future<WorkSessionCoordinates?> currentCoordinates();
}

class DeviceWorkSessionLocationSource implements WorkSessionLocationSource {
  DeviceWorkSessionLocationSource(this._locationService);

  final LocationService _locationService;

  @override
  Future<WorkSessionCoordinates?> currentCoordinates() async {
    final position = await _locationService.getCurrentLocation();
    if (position == null) return null;

    return WorkSessionCoordinates(
      latitude: position.latitude,
      longitude: position.longitude,
    );
  }
}
