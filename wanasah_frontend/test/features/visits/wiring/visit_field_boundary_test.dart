import 'dart:io';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('presentation consumes use-cases without transport, Batch IDs or peer feature dependencies', () {
    final files = Directory('lib/features/visits/presentation')
      .listSync(recursive: true).whereType<File>()
      .where((file) => file.path.endsWith('.dart'));
    for (final file in files) {
      final source = file.readAsStringSync();
      expect(source, isNot(contains('ApiClient')), reason: file.path);
      expect(source, isNot(contains('api_client.dart')), reason: file.path);
      expect(RegExp(r'\b(batch_id|batchId|resolution_token|resolutionToken)\b').hasMatch(source),
        isFalse, reason: file.path);
      for (final peer in ['list', 'custody', 'shops', 'recovery', 'work_session']) {
        expect(RegExp("import .*features/$peer/|import .*\\.\\./$peer/").hasMatch(source),
          isFalse, reason: file.path);
      }
    }
    final screen = File('lib/screens/visit_screen.dart').readAsStringSync();
    expect(screen, contains('confirmVisitFieldSubmission('));
    expect(screen, isNot(contains('coordinator.resolve(')));
    expect(screen, isNot(contains('expectedNewTotalBalance')));
    expect(screen, isNot(contains('cashEntered > state.netInvoice')));
  });

  test('new application integration has no widget, Bloc or LocalDatabase imports and creates no UUID', () {
    for (final name in ['visit_return_submission', 'visit_sale_confirmation',
      'visit_command_evidence', 'visit_money_input', 'visit_submission_service']) {
      final source = File('lib/features/visits/application/$name.dart').readAsStringSync();
      expect(RegExp(r"import .*flutter|import .*bloc|import .*local_database").hasMatch(source), isFalse);
      expect(source, isNot(contains('Uuid')));
      expect(source, isNot(contains('v4(')));
      expect(source, isNot(contains("['request_id']")));
      expect(source, isNot(contains('batch_id')));
    }
    for (final file in Directory('lib/features/visits/presentation/invoice')
        .listSync().whereType<File>()) {
      expect(RegExp(r'\bdouble\b|toDouble|double.parse|num.parse').hasMatch(file.readAsStringSync()),
        isFalse, reason: file.path);
    }
  });
}
