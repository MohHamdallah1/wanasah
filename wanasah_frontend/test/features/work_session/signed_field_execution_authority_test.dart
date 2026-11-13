import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/work_session/data/execution_context.dart';
import 'package:wanasah_frontend/features/work_session/data/signed_field_execution_authority.dart';

ExecutionContextProof proof(int route, int period, int revision, int epoch) =>
    ExecutionContextProof(
      sessionId: 11,
      routeId: route,
      periodId: period,
      vehicleId: route == 2 ? 22 : 21,
      vehicleLocationId: route == 2 ? 222 : 211,
      assignmentRevision: revision,
      custodyEpochId: epoch,
    );

DioException offline() => DioException(
      requestOptions: RequestOptions(path: '/driver/sessions/execution-context'),
      type: DioExceptionType.connectionError,
    );

DioException refused(int code) => DioException(
      requestOptions: RequestOptions(path: '/driver/sessions/execution-context'),
      response: Response<dynamic>(
        requestOptions: RequestOptions(path: '/driver/sessions/execution-context'),
        statusCode: code,
      ),
      type: DioExceptionType.badResponse,
    );

void main() {
  test('FIELD signed period is durable per canonical principal, frozen on ABA', () async {
    final store = <String, String>{};
    var owner = 'company1:principal2:rep3:driver4';
    var live = proof(1, 10, 2, 50);
    var isOffline = false;
    final authority = SignedFieldExecutionAuthority(
      ownerKey: () async => owner,
      readRemote: () async {
        if (isOffline) throw offline();
        return live;
      },
      readSaved: (key) async => store[key],
      writeSaved: (key, value) async { store[key] = value; },
      deleteSaved: (key) async { store.remove(key); },
    );

    final a1 = (await authority.read())!;
    isOffline = true;
    expect((await authority.read())!.toJson(), a1.toJson());
    live = proof(2, 11, 3, 51);
    isOffline = false;
    final b = (await authority.read())!;
    expect(b.periodId, 11);
    expect(a1.requestHeaders['X-Execution-Period-ID'], '10');
    live = proof(1, 12, 4, 52);
    expect((await authority.read())!.periodId, 12);
    expect(a1.requestHeaders['X-Assignment-Context-Revision'], '2');
    isOffline = true;
    final a2 = (await authority.read())!;
    expect(a2.periodId, 12);
    expect(a2.requestHeaders, isNot(a1.requestHeaders));
    // Identity rotated: yesterday's source period cannot be borrowed.
    owner = 'company1:principal99:rep3:driver4';
    expect(() => authority.read(), throwsA(isA<DioException>()));
  });

  test('403, 409 and 500 never use cached signed proof', () async {
    final store = <String, String>{};
    DioException? deny;
    final authority = SignedFieldExecutionAuthority(
      ownerKey: () async => 'signed-owner',
      readRemote: () async {
        if (deny != null) throw deny;
        return proof(1, 42, 2, 10);
      },
      readSaved: (key) async => store[key],
      writeSaved: (key, value) async { store[key] = value; },
      deleteSaved: (key) async { store.remove(key); },
    );
    expect((await authority.read())!.periodId, 42);
    for (final status in <int>[401, 403, 409, 500]) {
      deny = refused(status);
      await expectLater(authority.read(), throwsA(isA<DioException>()));
    }
  });

  test('successful S2 start caches NEW period; legacy/no-period clears it', () async {
    final store = <String, String>{};
    final authority = SignedFieldExecutionAuthority(
      ownerKey: () async => 'signed-owner',
      readRemote: () async => throw offline(),
      readSaved: (key) async => store[key],
      writeSaved: (key, value) async { store[key] = value; },
      deleteSaved: (key) async { store.remove(key); },
    );
    await authority.captureSuccessfulStart(<String, dynamic>{
      'session_id': 11,
      'execution_context': proof(1, 500, 5, 60).toJson(),
    });
    expect((await authority.read())!.periodId, 500);
    await authority.captureSuccessfulStart(<String, dynamic>{
      'session_id': 12, 'execution_context': null,
    });
    await expectLater(authority.read(), throwsA(isA<DioException>()));
  });

  test('no stale cache after server-confirmed legacy V1 route', () async {
    final store = <String, String>{};
    ExecutionContextProof? active = proof(1, 50, 2, 10);
    final authority = SignedFieldExecutionAuthority(
      ownerKey: () async => 'signed-owner',
      readRemote: () async => active,
      readSaved: (key) async => store[key],
      writeSaved: (key, value) async { store[key] = value; },
      deleteSaved: (key) async { store.remove(key); },
    );
    await authority.read();
    active = null;
    expect(await authority.read(), isNull);
    expect(store, isEmpty);
  });
}
