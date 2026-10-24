import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_reader.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_sync_coordinator.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_data_source.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_sync_executor.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_dashboard_scroll.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_status_utility.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_sync_feedback.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_strings.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_view_controller.dart';

void main() {
  RecoveryViewController controller(_Source source, [_Executor? executor]) =>
      RecoveryViewController(
        coordinator: RecoverySyncCoordinator(
          reader: RecoveryReader(dataSource: source),
          executor: executor ?? _Executor(),
        ),
      );

  RecoveryStatusUtility utility(
    RecoveryViewController value, [
    RecoveryServiceState service = RecoveryServiceState.available,
  ]) => RecoveryStatusUtility(
    controller: value,
    serviceState: service,
    onAfterSync: () {},
  );

  test('unread or failed inspection never claims no pending work', () async {
    final source = _Source();
    final view = controller(source);
    addTearDown(view.dispose);
    expect(utility(view).statusKey, RecoveryStringKey.checking);
    source.read = () async => throw StateError('inspection failed');
    await view.reload();
    expect(utility(view).statusKey, RecoveryStringKey.unavailableCompact);
    expect(view.snapshot, isNull);
  });

  test(
    'empty successful inspection, pending and blocked remain distinct',
    () async {
      final source = _Source();
      final view = controller(source);
      addTearDown(view.dispose);
      await view.reload();
      expect(utility(view).statusKey, RecoveryStringKey.noPending);
      source.rows = [_row('pending')];
      await view.reload();
      expect(utility(view).statusKey, RecoveryStringKey.pendingCompact);
      source.rows = [_row('pending'), _row('blocked', id: 2)];
      await view.reload();
      expect(utility(view).statusKey, RecoveryStringKey.blockedCompact);
      expect(view.snapshot!.pendingCount, 1);
      expect(view.snapshot!.blockedCount, 1);
    },
  );

  test(
    'failed inspection retains blocked evidence, IDs and diagnostics',
    () async {
      final source = _Source()..rows = [_row('blocked')];
      final view = controller(source);
      addTearDown(view.dispose);
      await view.reload();
      source.read = () async => throw StateError('unavailable');
      await view.reload();
      expect(view.readUnavailable, isTrue);
      expect(view.snapshot!.blocked.single.commandId, 'stable-command-1');
      expect(view.snapshot!.blocked.single.lastRequestId, 'trace-1');
      expect(utility(view).statusKey, RecoveryStringKey.blockedCompact);
    },
  );

  test(
    'service failure and reachability never become device internet claims',
    () async {
      final view = controller(_Source());
      addTearDown(view.dispose);
      await view.reload();
      expect(
        utility(view, RecoveryServiceState.unreachable).statusKey,
        RecoveryStringKey.unreachableCompact,
      );
      expect(
        utility(view, RecoveryServiceState.serviceFailure).statusKey,
        RecoveryStringKey.serviceCompact,
      );
      expect(
        utility(view, RecoveryServiceState.cached).statusKey,
        RecoveryStringKey.cachedCompact,
      );
    },
  );

  test(
    'ambiguous synchronization plus empty read does not report success',
    () async {
      final executor =
          _Executor()
            ..run =
                () async =>
                    throw DioException(
                      requestOptions: RequestOptions(path: '/synthetic'),
                      type: DioExceptionType.connectionTimeout,
                    );
      final view = controller(_Source(), executor);
      addTearDown(view.dispose);
      final result = await view.synchronize();
      expect(result!.disposition, RecoverySyncDisposition.unresolved);
      expect(utility(view).statusKey, RecoveryStringKey.unavailableCompact);
      await view.reload();
      expect(utility(view).statusKey, RecoveryStringKey.unavailableCompact);
      executor.run = () async => true;
      await view.synchronize();
      expect(utility(view).statusKey, RecoveryStringKey.noPending);
    },
  );

  test('shared surfaces cannot initiate duplicate concurrent sync', () async {
    final completion = Completer<bool>();
    final executor = _Executor()..run = () => completion.future;
    final view = controller(_Source(), executor);
    addTearDown(view.dispose);
    final first = view.synchronize();
    expect(view.syncing, isTrue);
    expect(await view.synchronize(), isNull);
    expect(executor.calls, 1);
    completion.complete(true);
    await first;
    expect(view.syncing, isFalse);
  });

  test('older inspection cannot erase newer blocked evidence', () async {
    final old = Completer<List<Map<String, dynamic>>>();
    final source = _Source()..read = () => old.future;
    final view = controller(source);
    addTearDown(view.dispose);
    final first = view.reload();
    source.read = () async => [_row('blocked')];
    await view.reload();
    old.complete([]);
    await first;
    expect(view.snapshot!.blockedCount, 1);
  });

  test(
    'disposing a shell during an inspection cannot notify a dead surface',
    () async {
      final old = Completer<List<Map<String, dynamic>>>();
      final view = controller(_Source()..read = () => old.future);
      final read = view.reload();
      view.dispose();
      old.complete([]);
      await expectLater(read, completes);
    },
  );

  testWidgets(
    'empty manual refresh stays silent while preserving canonical sync',
    (tester) async {
      final source = _Source();
      final executor = _Executor();
      final view = controller(source, executor);
      addTearDown(view.dispose);
      await view.reload();

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ar'),
          supportedLocales: const [Locale('ar')],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: Builder(
            builder:
                (context) => ElevatedButton(
                  onPressed:
                      () => refreshRecoveryWithFeedback(
                        context,
                        view,
                        () {},
                      ),
                  child: const Text('refresh'),
                ),
          ),
        ),
      );

      await tester.tap(find.text('refresh'));
      await tester.pumpAndSettle();

      expect(executor.calls, 1);
      expect(find.text('جاري مزامنة العمليات المحفوظة…'), findsNothing);
      expect(find.text('تمت المزامنة بالكامل.'), findsNothing);
    },
  );

  testWidgets(
    'pending manual refresh shows sync progress and completion feedback',
    (tester) async {
      final source = _Source()..rows = [_row('pending')];
      final completion = Completer<bool>();
      final executor = _Executor()..run = () => completion.future;
      final view = controller(source, executor);
      addTearDown(view.dispose);
      await view.reload();

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ar'),
          supportedLocales: const [Locale('ar')],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: Builder(
            builder:
                (context) => ElevatedButton(
                  onPressed:
                      () => refreshRecoveryWithFeedback(
                        context,
                        view,
                        () {},
                      ),
                  child: const Text('refresh'),
                ),
          ),
        ),
      );

      await tester.tap(find.text('refresh'));
      await tester.pump();
      expect(find.text('جاري مزامنة العمليات المحفوظة…'), findsOneWidget);

      source.rows = [];
      completion.complete(true);
      await tester.pump();
      await tester.pump();

      expect(executor.calls, 1);
      expect(find.text('تمت المزامنة بالكامل.'), findsOneWidget);
    },
  );

  testWidgets(
    'Home and global utility share one read model and retained details',
    (tester) async {
      final source =
          _Source()..rows = [_row('pending'), _row('blocked', id: 2)];
      final executor = _Executor();
      final view = controller(source, executor);
      addTearDown(view.dispose);
      await view.reload();
      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ar'),
          supportedLocales: const [Locale('ar')],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: Scaffold(
            body: Column(
              children: [
                utility(view, RecoveryServiceState.serviceFailure),
                Expanded(
                  child: RecoveryDashboardScroll(
                    controller: view,
                    onAfterSync: () {},
                    children: const [Text('Home')],
                  ),
                ),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(source.calls, 1);
      expect(executor.calls, 0);
      await tester.tap(find.byKey(const ValueKey('shell-sync-status')));
      await tester.pumpAndSettle();
      expect(find.text('تعذر تحديث الخدمة'), findsOneWidget);
      expect(find.textContaining('معلّقة:'), findsOneWidget);
      await tester.tap(find.text('عرض الأدلة المحفوظة'));
      await tester.pumpAndSettle();
      expect(find.textContaining('trace-2'), findsOneWidget);
      expect(find.textContaining('stable-command-2'), findsOneWidget);
      expect(executor.calls, 0);
      expect(tester.takeException(), isNull);
    },
  );
}

Map<String, dynamic> _row(String state, {int id = 1}) => {
  'id': id,
  'type': 'submit_sale',
  'state': state,
  'command_id': 'stable-command-$id',
  'payload': '{}',
  'created_at': '2026-10-24T08:00:00Z',
  'attempt_count': 1,
  'last_error_code': state == 'blocked' ? 'VISIT_STATE_CONFLICT' : null,
  'last_request_id': 'trace-$id',
};

class _Source implements RecoveryDataSource {
  List<Map<String, dynamic>> rows = [];
  Future<List<Map<String, dynamic>>> Function()? read;
  int calls = 0;
  @override
  Future<List<Map<String, dynamic>>> readUnresolvedRows() async {
    calls++;
    return read != null ? await read!() : rows;
  }
}

class _Executor implements RecoverySyncExecutor {
  Future<bool> Function() run = () async => true;
  int calls = 0;
  @override
  Future<bool> synchronize() {
    calls++;
    return run();
  }
}
