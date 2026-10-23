import 'dart:async';
import 'package:geolocator/geolocator.dart';
import 'location_failure.dart';

export 'location_failure.dart';

/// Narrow device boundary; no permission cache or domain eligibility policy.
abstract interface class LocationDeviceSource {
  Future<bool> isServiceEnabled();
  Future<LocationPermission> checkPermission();
  Future<LocationPermission> requestPermission();
  Future<Position?> lastKnownPosition();
  Future<Position> currentPosition();
}

class _GeolocatorSource implements LocationDeviceSource {
  const _GeolocatorSource();
  @override
  Future<bool> isServiceEnabled() => Geolocator.isLocationServiceEnabled();
  @override
  Future<LocationPermission> checkPermission() => Geolocator.checkPermission();
  @override
  Future<LocationPermission> requestPermission() => Geolocator.requestPermission();
  @override
  Future<Position?> lastKnownPosition() => Geolocator.getLastKnownPosition();
  @override
  Future<Position> currentPosition() =>
      Geolocator.getCurrentPosition(desiredAccuracy: LocationAccuracy.high);
}

class LocationService {
  static final LocationService instance =
      LocationService.withSource(const _GeolocatorSource());

  LocationService.withSource(LocationDeviceSource source, {DateTime Function()? now})
      : _source = source, _now = now ?? DateTime.now;

  final LocationDeviceSource _source;
  final DateTime Function() _now;

  Future<Position?> getCurrentLocation() async {
    try {
      if (!await _source.isServiceEnabled()) {
        throw const LocationFailure(LocationFailureKind.serviceDisabled);
      }
      var permission = await _source.checkPermission();
      if (permission == LocationPermission.deniedForever) {
        throw const LocationFailure(LocationFailureKind.permissionDeniedForever);
      }
      if (permission == LocationPermission.denied) {
        permission = await _source.requestPermission();
        if (permission == LocationPermission.denied) {
          throw const LocationFailure(LocationFailureKind.permissionDenied);
        }
        if (permission == LocationPermission.deniedForever) {
          throw const LocationFailure(LocationFailureKind.permissionDeniedForever);
        }
      }
      final last = await _source.lastKnownPosition();
      if (last != null && last.isMocked) {
        throw const LocationFailure(LocationFailureKind.mockedLocation);
      }
      if (last != null && _now().difference(last.timestamp).abs().inSeconds < 60) {
        return last;
      }
      final current = await _source.currentPosition()
          .timeout(const Duration(seconds: 8));
      if (current.isMocked) {
        throw const LocationFailure(LocationFailureKind.mockedLocation);
      }
      return current;
    } on LocationFailure {
      rethrow;
    } on TimeoutException catch (error, stack) {
      Error.throwWithStackTrace(LocationFailure(LocationFailureKind.timeout,
        cause: error, causeStackTrace: stack), stack);
    } on LocationServiceDisabledException catch (error, stack) {
      Error.throwWithStackTrace(LocationFailure(LocationFailureKind.serviceDisabled,
        cause: error, causeStackTrace: stack), stack);
    } on PermissionDeniedException catch (error, stack) {
      Error.throwWithStackTrace(LocationFailure(LocationFailureKind.permissionDenied,
        cause: error, causeStackTrace: stack), stack);
    } catch (error, stack) {
      Error.throwWithStackTrace(LocationFailure(LocationFailureKind.unexpected,
        cause: error, causeStackTrace: stack), stack);
    }
  }
}
