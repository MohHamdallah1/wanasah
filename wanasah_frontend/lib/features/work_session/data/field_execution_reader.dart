import '../../../core/network/api_client.dart';
import 'execution_context.dart';

/// Read the exact M03 signed FIELD envelope (never the legacy last route).
/// The endpoint will be available only after M03 merges; no silent fallback.
class FieldExecutionReader {
  const FieldExecutionReader({required this.readResponse});

  factory FieldExecutionReader.withApiClient(ApiClient client) =>
      FieldExecutionReader(readResponse: () async =>
          (await client.get<Object?>('/driver/sessions/execution-context')).data);

  final Future<Object?> Function() readResponse;

  Future<ExecutionContextProof?> read() async {
    final raw = await readResponse();
    if (raw is! Map || raw['active_session_found'] is! bool) {
      throw const FormatException('Invalid FIELD execution-context response');
    }
    if (raw['active_session_found'] != true) {
      throw const FormatException('No active FIELD WorkSession');
    }
    // A signed M03 period is mandatory for canonical mutations. Only a
    // backend-confirmed ACTIVE legacy V1 session may return null here, and
    // backend independently denies missing proof on canonical visits.
    if (raw['execution_context'] == null) return null;
    return ExecutionContextProof.fromResponse(raw);
  }
}
