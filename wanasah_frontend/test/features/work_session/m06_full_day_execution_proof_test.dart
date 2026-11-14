import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/work_session/data/execution_context.dart';
import 'package:wanasah_frontend/features/work_session/data/signed_field_execution_authority.dart';

ExecutionContextProof signed({
  required int session,
  required int route,
  required int period,
  required int vehicle,
  required int location,
  required int revision,
  required int epoch,
}) => ExecutionContextProof(
  sessionId: session,
  routeId: route,
  periodId: period,
  vehicleId: vehicle,
  vehicleLocationId: location,
  assignmentRevision: revision,
  custodyEpochId: epoch,
);

DioException offline() => DioException(
  requestOptions: RequestOptions(path: '/driver/sessions/execution-context'),
  type: DioExceptionType.connectionError,
);

void main() {
  test(
    'M06 FIELD S1 paused A, resumed A, B, A and settled S2 reject old offline proofs',
    () async {
      final saved = <String, String>{};
      var owner = 'company-a:field-principal-khaled';
      ExecutionContextProof? current = signed(
        session: 101,
        route: 11,
        period: 201,
        vehicle: 31,
        location: 41,
        revision: 2,
        epoch: 1,
      );
      var disconnected = false;
      final reader = SignedFieldExecutionAuthority(
        ownerKey: () async => owner,
        readRemote: () async {
          if (disconnected) throw offline();
          return current;
        },
        readSaved: (key) async => saved[key],
        writeSaved: (key, value) async {
          saved[key] = value;
        },
        deleteSaved: (key) async {
          saved.remove(key);
        },
      );

      final a1 = (await reader.read())!;
      disconnected = true;
      expect((await reader.read())!.requestHeaders, a1.requestHeaders);
      disconnected = false;

      // PAUSE has no executable FIELD period. A signed null read invalidates
      // previous offline authority; previous queued request body remains frozen.
      current = null;
      expect(await reader.read(), isNull);
      disconnected = true;
      await expectLater(reader.read(), throwsA(isA<DioException>()));
      disconnected = false;

      current = signed(
        session: 101,
        route: 11,
        period: 203,
        vehicle: 31,
        location: 41,
        revision: 4,
        epoch: 1,
      );
      final resumedA = (await reader.read())!;
      expect(resumedA.requestHeaders, isNot(a1.requestHeaders));

      current = signed(
        session: 101,
        route: 12,
        period: 204,
        vehicle: 32,
        location: 42,
        revision: 2,
        epoch: 1,
      );
      final b = (await reader.read())!;
      expect(b.vehicleId, 32);
      expect(b.sessionId, a1.sessionId);
      expect(b.requestHeaders, isNot(resumedA.requestHeaders));

      current = signed(
        session: 101,
        route: 11,
        period: 205,
        vehicle: 31,
        location: 41,
        revision: 6,
        epoch: 1,
      );
      final aAgain = (await reader.read())!;
      expect(aAgain.periodId, isNot(a1.periodId));
      expect(aAgain.requestHeaders, isNot(a1.requestHeaders));
      expect(aAgain.requestHeaders, isNot(b.requestHeaders));

      // Once S1 ends, the server's missing current proof is authoritative.
      current = null;
      expect(await reader.read(), isNull);
      disconnected = true;
      await expectLater(reader.read(), throwsA(isA<DioException>()));
      disconnected = false;

      // Only a successful canonical 201 S2 can seed the next offline proof.
      final s2 = signed(
        session: 102,
        route: 11,
        period: 206,
        vehicle: 31,
        location: 41,
        revision: 7,
        epoch: 1,
      );
      await reader.captureSuccessfulStart(<String, dynamic>{
        'session_id': 102,
        'execution_context': s2.toJson(),
      });
      disconnected = true;
      expect((await reader.read())!.requestHeaders, s2.requestHeaders);
      expect(a1.requestHeaders['X-Execution-Period-ID'], '201');
      expect(b.requestHeaders['X-Execution-Period-ID'], '204');

      // A new identity may not inherit any previously signed A/B/A or S2 proof.
      owner = 'company-b:field-principal-other';
      await expectLater(reader.read(), throwsA(isA<DioException>()));
    },
  );
}
