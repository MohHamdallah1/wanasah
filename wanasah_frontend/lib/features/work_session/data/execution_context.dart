/// One immutable, signed-server-derived FIELD route/vehicle assignment.
/// Do not derive it from a legacy route, car name, or the current UI tab.
class ExecutionContextProof {
  const ExecutionContextProof({
    required this.sessionId,
    required this.routeId,
    required this.periodId,
    required this.vehicleId,
    required this.vehicleLocationId,
    required this.assignmentRevision,
    required this.custodyEpochId,
  });

  final int sessionId;
  final int routeId;
  final int periodId;
  final int vehicleId;
  final int vehicleLocationId;
  final int assignmentRevision;
  final int custodyEpochId;

  static int _positive(dynamic value, String field) {
    if (value is! int || value <= 0) {
      throw FormatException('Invalid FIELD execution $field');
    }
    return value;
  }

  static ExecutionContextProof fromResponse(Object? data) {
    if (data is! Map) {
      throw const FormatException('Invalid signed FIELD execution context');
    }
    final raw = data['execution_context'];
    if (raw is! Map) {
      throw const FormatException('No current signed FIELD execution period');
    }
    final proof = ExecutionContextProof.fromJson(Map<String, dynamic>.from(raw));
    final session = data['session_id'];
    if (session != null && session != proof.sessionId) {
      throw const FormatException('FIELD session and period mismatch');
    }
    return proof;
  }

  factory ExecutionContextProof.fromJson(Map<String, dynamic> json) {
    return ExecutionContextProof(
      sessionId: _positive(json['session_id'], 'session_id'),
      routeId: _positive(json['route_id'], 'route_id'),
      periodId: _positive(json['period_id'], 'period_id'),
      vehicleId: _positive(json['vehicle_id'], 'vehicle_id'),
      vehicleLocationId:
          _positive(json['vehicle_location_id'], 'vehicle_location_id'),
      assignmentRevision: _positive(
        json['assignment_context_revision'], 'assignment_context_revision'),
      custodyEpochId: _positive(json['custody_epoch_id'], 'custody_epoch_id'),
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
    'session_id': sessionId,
    'route_id': routeId,
    'period_id': periodId,
    'vehicle_id': vehicleId,
    'vehicle_location_id': vehicleLocationId,
    'assignment_context_revision': assignmentRevision,
    'custody_epoch_id': custodyEpochId,
  };

  /// No automatic update to the current A/B/A envelope is permitted during
  /// a queued command retry; old committed body carries these exact values.
  Map<String, String> get requestHeaders => <String, String>{
    'X-Execution-Period-ID': periodId.toString(),
    'X-Assignment-Context-Revision': assignmentRevision.toString(),
    'X-Vehicle-Custody-Epoch-ID': custodyEpochId.toString(),
  };
}
