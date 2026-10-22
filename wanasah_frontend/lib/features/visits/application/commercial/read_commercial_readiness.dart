import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';

import '../../data/visit_field_client.dart';
import '../../domain/commercial/commercial_readiness.dart';
import 'commercial_readiness_outcome.dart';

typedef CommercialReadinessRead = Future<CommercialReadiness> Function(int visitId);

class ReadCommercialReadiness {
  const ReadCommercialReadiness({required CommercialReadinessRead read})
    : _read = read;

  factory ReadCommercialReadiness.fromClient(VisitFieldClient client) =>
      ReadCommercialReadiness(read: client.commercialState);

  final CommercialReadinessRead _read;

  Future<CommercialReadinessOutcome> execute(int visitId) async {
    try {
      final readiness = await _read(visitId);
      return switch (readiness.status) {
        CommercialReadinessStatus.ready => CommercialReady(readiness),
        CommercialReadinessStatus.actionRequired =>
          CommercialActionRequired(readiness),
      };
    } on ApiFailureException catch (error) {
      return CommercialReadinessFailed(error.apiFailure);
    } on FormatException {
      return const CommercialReadinessInvalidResponse();
    }
  }
}
