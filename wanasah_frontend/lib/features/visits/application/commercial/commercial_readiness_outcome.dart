import 'package:wanasah_frontend/core/network/api_failure.dart';

import '../../domain/commercial/commercial_readiness.dart';

sealed class CommercialReadinessOutcome {
  const CommercialReadinessOutcome();

  /// Tax prerequisite only. Failures/unknown contracts never count as ready.
  bool get taxSetupReady => false;
}

final class CommercialReady extends CommercialReadinessOutcome {
  const CommercialReady(this.readiness);
  final CommercialReadiness readiness;

  @override
  bool get taxSetupReady => true;
}

final class CommercialActionRequired extends CommercialReadinessOutcome {
  const CommercialActionRequired(this.readiness);
  final CommercialReadiness readiness;

  String get code => readiness.code!;
  String get requiredAction => readiness.requiredAction!;
}

final class CommercialReadinessFailed extends CommercialReadinessOutcome {
  const CommercialReadinessFailed(this.failure);
  final ApiFailure failure;
}

final class CommercialReadinessInvalidResponse extends CommercialReadinessOutcome {
  const CommercialReadinessInvalidResponse();
}
