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
    if (raw['execution_context'] == null) return null; // No permission to sell.
    return ExecutionContextProof.fromResponse(raw);
  }
}
