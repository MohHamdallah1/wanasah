import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/auth/auth_bloc.dart';
import 'package:wanasah_frontend/blocs/auth/auth_event.dart';
import 'package:wanasah_frontend/screens/login_screen.dart';

class _RecordingAuthBloc extends AuthBloc {
  final List<AuthEvent> recordedEvents = <AuthEvent>[];

  @override
  void add(AuthEvent event) {
    recordedEvents.add(event);
  }
}

Widget _loginHarness(_RecordingAuthBloc bloc) {
  return MaterialApp(
    home: BlocProvider<AuthBloc>.value(
      value: bloc,
      child: const LoginScreen(),
    ),
  );
}

Future<_RecordingAuthBloc> _pumpLogin(WidgetTester tester) async {
  final bloc = _RecordingAuthBloc();
  addTearDown(bloc.close);
  await tester.pumpWidget(_loginHarness(bloc));
  return bloc;
}

void main() {
  group('LoginScreen release credential safety', () {
    testWidgets('company code, username and password start empty', (tester) async {
      await _pumpLogin(tester);

      final fields = tester
          .widgetList<TextField>(find.byType(TextField))
          .toList(growable: false);

      expect(fields, hasLength(3));
      expect(
        fields.map((field) => field.controller?.text).toList(),
        <String?>['', '', ''],
      );
    });

    testWidgets('company code remains mandatory before LoginRequested', (tester) async {
      final bloc = await _pumpLogin(tester);
      final fields = find.byType(TextField);

      await tester.enterText(fields.at(1), 'field-user');
      await tester.enterText(fields.at(2), 'secret');
      await tester.tap(find.widgetWithText(ElevatedButton, 'تسجيل الدخول'));
      await tester.pump();

      expect(
        find.text('الرجاء إدخال رمز الشركة واسم المستخدم وكلمة المرور'),
        findsOneWidget,
      );
      expect(bloc.recordedEvents, isEmpty);
    });

    testWidgets('LoginRequested preserves password exactly and keeps server tenant input', (
      tester,
    ) async {
      final bloc = await _pumpLogin(tester);
      final fields = find.byType(TextField);
      const rawPassword = '  كلمة سر with spaces  ';

      await tester.enterText(fields.at(0), '  WNS-77  ');
      await tester.enterText(fields.at(1), '  field-user  ');
      await tester.enterText(fields.at(2), rawPassword);
      await tester.tap(find.widgetWithText(ElevatedButton, 'تسجيل الدخول'));
      await tester.pump();

      expect(bloc.recordedEvents, hasLength(1));
      final event = bloc.recordedEvents.single;
      expect(event, isA<LoginRequested>());

      final login = event as LoginRequested;
      expect(login.companyCode, 'WNS-77');
      expect(login.username, 'field-user');
      expect(login.password, rawPassword);
    });

    test('source contains no distributed debug credential prefill', () {
      final source = File('lib/screens/login_screen.dart').readAsStringSync();

      expect(source, isNot(contains('kDebugMode')));
      expect(source, isNot(contains("package:flutter/foundation.dart")));
      expect(source, isNot(contains("'WNS-01'")));
      expect(source, isNot(contains("'testdriver'")));
      expect(source, isNot(contains("'password'")));
      expect(
        RegExp(r'TextEditingController\(\s*text:').hasMatch(source),
        isFalse,
      );
      expect(
        RegExp(r'TextEditingController\(\)').allMatches(source).length,
        3,
      );
    });
  });
}
