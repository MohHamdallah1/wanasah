import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Visit FIELD application imports only its own application/domain/data contracts and failure types', () {
    final roots = <Directory>[
      Directory('lib/features/visits/application/returns'),
      Directory('lib/features/visits/application/invoice'),
      Directory('lib/features/visits/application/commercial'),
    ];
    final feature = Directory('lib/features/visits').absolute.uri;
    final applicationPrefix = feature.resolve('application/').path;
    final domainPrefix = feature.resolve('domain/').path;
    final clientPath = feature.resolve('data/visit_field_client.dart').path;
    final files = roots
        .expand((root) => root.listSync(recursive: true).whereType<File>())
        .where((file) => file.path.endsWith('.dart'))
        .toList();
    expect(files, isNotEmpty);
    final directives = RegExp(r'''(?:import|export|part)\s+['"]([^'"]+)['"]''');
    for (final file in files) {
      final source = file.readAsStringSync();
      for (final match in directives.allMatches(source)) {
        final dependency = match.group(1)!;
        final sharedFailure = dependency ==
            'package:wanasah_frontend/core/network/api_failure.dart' ||
            dependency == 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
        final relative = !dependency.contains(':');
        final resolved = relative ? file.absolute.uri.resolve(dependency).path : '';
        final ownContract = relative && (
          resolved.startsWith(applicationPrefix) ||
          resolved.startsWith(domainPrefix) ||
          resolved == clientPath
        );
        expect(sharedFailure || ownContract, isTrue,
          reason: 'Forbidden application dependency: $dependency');
      }
      expect(RegExp(r'\b(LocalDatabase|SyncRepository|Widget|Bloc)\b').hasMatch(source),
        isFalse, reason: file.path);
      expect(RegExp(r'\b(batch_id|batchId)\b').hasMatch(source),
        isFalse, reason: file.path);
      expect(RegExp(r'(double\.parse|num\.parse|\.toDouble\s*\()').hasMatch(source),
        isFalse, reason: file.path);
    }
  });
}
