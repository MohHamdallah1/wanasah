import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/work_session/data/execution_context.dart';
import 'package:wanasah_frontend/features/work_session/data/field_execution_reader.dart';

Map<String, dynamic> period({int revision = 3, int epoch = 15}) =>
    <String, dynamic>{
      'session_id': 11, 'route_id': 23, 'period_id': 47,
      'vehicle_id': 6, 'vehicle_location_id': 69,
      'assignment_context_revision': revision, 'custody_epoch_id': epoch,
    };

void main() {
  test('signed FIELD period is immutable and carries three exact ABA headers',
      () {
    final proof = ExecutionContextProof.fromResponse(<String, dynamic>{
      'active_session_found': true, 'session_id': 11,
      'execution_context': period(),
    });
    expect(proof.requestHeaders, <String, String>{
      'X-Execution-Period-ID': '47',
      'X-Assignment-Context-Revision': '3',
      'X-Vehicle-Custody-Epoch-ID': '15',
    });
    expect(proof.toJson(), period());
    expect(proof.custodyEpochId, 15);
  });

  test('A/B/A new revision is not equal to old original command context', () {
    final a1 = ExecutionContextProof.fromJson(period());
    final a2 = ExecutionContextProof.fromJson(period(revision: 5, epoch: 17));
    expect(a1.requestHeaders, isNot(a2.requestHeaders));
    expect(a1.assignmentRevision, 3);
  });

  test('missing or malformed signed fields fail closed', () {
    expect(() => ExecutionContextProof.fromJson(<String, dynamic>{
      ...period(), 'custody_epoch_id': null,
    }), throwsFormatException);
    expect(() => ExecutionContextProof.fromResponse(<String, dynamic>{
      'session_id': 12, 'execution_context': period(),
    }), throwsFormatException);
    expect(() => ExecutionContextProof.fromResponse(<String, dynamic>{
      'session_id': 11, 'execution_context': null,
    }), throwsFormatException);
  });

  test('no current period is null and never fabricated from last route', () async {
    final reader = FieldExecutionReader(readResponse: () async =>
      <String, dynamic>{
        'active_session_found': true, 'session_id': 11,
        'execution_context': null,
        'route_id': 23, 'vehicle_id': 6,
      });
    expect(await reader.read(), isNull);
  });
}
