import 'dart:async';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:wanasah_frontend/services/location_service.dart';

final now = DateTime.utc(2026, 10, 23, 12);
Position position({bool mocked = false, int ageSeconds = 0}) => Position(
  latitude: 31.95, longitude: 35.91, timestamp: now.subtract(Duration(seconds: ageSeconds)),
  accuracy: 1, altitude: 0, altitudeAccuracy: 1, heading: 0, headingAccuracy: 1,
  speed: 0, speedAccuracy: 1, isMocked: mocked,
);

class Device implements LocationDeviceSource {
  bool enabled = true;
  LocationPermission permission = LocationPermission.whileInUse;
  LocationPermission requested = LocationPermission.denied;
  Position? last;
  Position? current;
  Object? failure;
  String failureAt = 'current';
  int requests = 0, currentReads = 0;
  Completer<Position>? pending;

  void fail(String stage) {
    if (failureAt == stage && failure != null) {
      throw failure!;
    }
  }
  @override
  Future<bool> isServiceEnabled() async { fail('enabled'); return enabled; }
  @override
  Future<LocationPermission> checkPermission() async { fail('permission'); return permission; }
  @override
  Future<LocationPermission> requestPermission() async {
    requests++; fail('request'); return requested;
  }
  @override
  Future<Position?> lastKnownPosition() async { fail('last'); return last; }
  @override
  Future<Position> currentPosition() async {
    currentReads++; fail('current');
    return pending?.future ?? Future.value(current ?? position());
  }
}

TypeMatcher<LocationFailure> kind(LocationFailureKind expected) =>
    isA<LocationFailure>().having((failure) => failure.kind, 'kind', expected);

void main() {
  test('disabled service is typed before permission or position access', () async {
    final device = Device()..enabled = false;
    await expectLater(LocationService.withSource(device).getCurrentLocation(),
      throwsA(kind(LocationFailureKind.serviceDisabled)));
    expect(device.requests, 0);
    expect(device.currentReads, 0);
  });
  test('denied permission requests once then returns typed denial', () async {
    final device = Device()..permission = LocationPermission.denied;
    await expectLater(LocationService.withSource(device).getCurrentLocation(),
      throwsA(kind(LocationFailureKind.permissionDenied)));
    expect(device.requests, 1);
    expect(device.currentReads, 0);
  });
  test('denied forever fails early without requesting permission', () async {
    final device = Device()..permission = LocationPermission.deniedForever;
    await expectLater(LocationService.withSource(device).getCurrentLocation(),
      throwsA(kind(LocationFailureKind.permissionDeniedForever)));
    expect(device.requests, 0);
  });
  test('denied then permanently denied remains typed', () async {
    final device = Device()..permission = LocationPermission.denied
      ..requested = LocationPermission.deniedForever;
    await expectLater(LocationService.withSource(device).getCurrentLocation(),
      throwsA(kind(LocationFailureKind.permissionDeniedForever)));
  });
  test('granted request continues to current position', () async {
    final device = Device()..permission = LocationPermission.denied
      ..requested = LocationPermission.whileInUse;
    expect(await LocationService.withSource(device).getCurrentLocation(), isA<Position>());
    expect(device.requests, 1);
  });
  test('recent last-known location is returned without fresh lookup', () async {
    final last = position(ageSeconds: 59);
    final device = Device()..last = last;
    expect(await LocationService.withSource(device, now: () => now).getCurrentLocation(), same(last));
    expect(device.currentReads, 0);
  });
  test('60-second-old last-known location requires fresh lookup', () async {
    final current = position();
    final device = Device()..last = position(ageSeconds: 60)..current = current;
    expect(await LocationService.withSource(device, now: () => now).getCurrentLocation(), same(current));
    expect(device.currentReads, 1);
  });
  for (final useLast in [true, false]) {
    test('real Position.isMocked rejects ${useLast ? 'cached' : 'fresh'} position', () async {
      final device = Device();
      if (useLast) { device.last = position(mocked: true, ageSeconds: 90); }
      else { device.current = position(mocked: true); }
      await expectLater(LocationService.withSource(device, now: () => now).getCurrentLocation(),
        throwsA(kind(LocationFailureKind.mockedLocation)));
    });
  }
  for (final entry in [
    (TimeoutException('arbitrary message'), LocationFailureKind.timeout),
    (LocationServiceDisabledException(), LocationFailureKind.serviceDisabled),
    (PermissionDeniedException('arbitrary message'), LocationFailureKind.permissionDenied),
  ]) {
    test('typed platform ${entry.$2.name} maps regardless of message', () async {
      final device = Device()..failure = entry.$1;
      await expectLater(LocationService.withSource(device).getCurrentLocation(),
        throwsA(kind(entry.$2).having((failure) => failure.cause, 'cause', same(entry.$1))));
    });
  }
  testWidgets('current-position lookup retains the eight-second timeout', (tester) async {
    final device = Device()..pending = Completer<Position>();
    Object? caught;
    final future = LocationService.withSource(device).getCurrentLocation()
      .catchError((Object error) { caught = error; return null; });
    await tester.pump();
    await tester.pump(const Duration(seconds: 8));
    await future;
    expect(caught, kind(LocationFailureKind.timeout));
  });
  test('arbitrary code-looking exception stays unexpected and preserves diagnostics', () async {
    final error = StateError('FAKE_GPS_DETECTED GPS_TIMEOUT GPS_DENIED');
    final device = Device()..failure = error;
    try {
      await LocationService.withSource(device).getCurrentLocation();
      fail('Expected typed failure');
    } on LocationFailure catch (failure) {
      expect(failure.kind, LocationFailureKind.unexpected);
      expect(failure.code, 'GPS_UNEXPECTED');
      expect(failure.cause, same(error));
      expect(failure.causeStackTrace, isNotNull);
      expect(failure.toString(), isNot(contains('FAKE_GPS_DETECTED')));
    }
  });
  test('initial platform failures are also mapped by type', () async {
    final error = LocationServiceDisabledException();
    final device = Device()..failureAt = 'enabled'..failure = error;
    await expectLater(LocationService.withSource(device).getCurrentLocation(),
      throwsA(kind(LocationFailureKind.serviceDisabled)));
  });
  test('generic unexpected error never becomes a timeout', () async {
    final device = Device()..failure = ArgumentError('GPS_TIMEOUT');
    await expectLater(LocationService.withSource(device).getCurrentLocation(),
      throwsA(kind(LocationFailureKind.unexpected)));
  });
  test('LocationService contains no exception-text classification', () {
    final source = File('lib/services/location_service.dart').readAsStringSync();
    expect(source, isNot(contains('toString()')));
    expect(source, isNot(contains('.contains(')));
    expect(source, isNot(contains('throw Exception(')));
  });
}
