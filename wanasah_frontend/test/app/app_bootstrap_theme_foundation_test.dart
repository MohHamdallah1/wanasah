import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/app/bootstrap/app_environment.dart';
import 'package:wanasah_frontend/app/bootstrap/app_error_handlers.dart';
import 'package:wanasah_frontend/app/theme/app_system_ui.dart';
import 'package:wanasah_frontend/app/theme/app_theme.dart';
import 'package:wanasah_frontend/app/theme/app_tokens.dart';

void main() {
  group('App bootstrap environment policy', () {
    test('missing dotenv is fatal in Release policy', () async {
      final loader = AppEnvironmentLoader(
        isReleaseMode: true,
        fileLoader: () async {
          throw StateError('missing');
        },
        logSink: (_) {},
      );

      await expectLater(
        loader.load(),
        throwsA(
          isA<Exception>().having(
            (error) => error.toString(),
            'message',
            contains(
              'CRITICAL ERROR: .env file is missing in Release mode!',
            ),
          ),
        ),
      );
    });

    test('missing dotenv remains nonfatal in Debug policy', () async {
      final logs = <String>[];
      final loader = AppEnvironmentLoader(
        isReleaseMode: false,
        fileLoader: () async {
          throw StateError('missing');
        },
        logSink: logs.add,
      );

      await expectLater(loader.load(), completes);

      expect(logs, hasLength(1));
      expect(logs.single, contains('ملف .env غير موجود'));
    });

    test('successful dotenv load produces no fallback warning', () async {
      var calls = 0;
      final logs = <String>[];
      final loader = AppEnvironmentLoader(
        isReleaseMode: false,
        fileLoader: () async {
          calls += 1;
        },
        logSink: logs.add,
      );

      await loader.load();

      expect(calls, 1);
      expect(logs, isEmpty);
    });
  });

  group('App error ownership', () {
    test('installs Flutter, platform and custom ErrorWidget handlers', () {
      final previousFlutterHandler = FlutterError.onError;
      final previousPlatformHandler = ui.PlatformDispatcher.instance.onError;
      final previousErrorWidgetBuilder = ErrorWidget.builder;

      addTearDown(() {
        FlutterError.onError = previousFlutterHandler;
        ui.PlatformDispatcher.instance.onError = previousPlatformHandler;
        ErrorWidget.builder = previousErrorWidgetBuilder;
      });

      AppErrorHandlers.install();

      expect(FlutterError.onError, isNotNull);
      expect(ui.PlatformDispatcher.instance.onError, isNotNull);

      final widget = ErrorWidget.builder(
        FlutterErrorDetails(
          exception: StateError('characterization-only'),
        ),
      );
      expect(widget, isA<MaterialApp>());
    });

    test('error owner preserves Sentry capture and debug presentation', () async {
      final source = await File(
        'lib/app/bootstrap/app_error_handlers.dart',
      ).readAsString();

      expect(
        RegExp(r'Sentry\.captureException').allMatches(source).length,
        2,
      );
      expect(source, contains('FlutterError.presentError(details)'));
      expect(
        source,
        contains('PlatformDispatcher.instance.onError'),
      );
      expect(source, contains('return true;'));
    });
  });

  group('Single Auth lifecycle and app composition', () {
    test('main.dart is a tiny bootstrap entrypoint', () async {
      final source = await File('lib/main.dart').readAsString();
      final nonEmptyLines =
          source
              .split('\n')
              .where((line) => line.trim().isNotEmpty)
              .length;

      expect(nonEmptyLines, lessThanOrEqualTo(4));
      expect(source, contains('AppBootstrap().run()'));
      expect(source, isNot(contains('SentryFlutter.init')));
      expect(source, isNot(contains('ApiClient.init')));
      expect(source, isNot(contains('ThemeData(')));
      expect(source, isNot(contains('MaterialApp(')));
      expect(source, isNot(contains('ErrorWidget.builder')));
    });

    test('app foundation contains exactly one AuthBloc construction', () async {
      final appFiles = Directory('lib/app')
          .listSync(recursive: true)
          .whereType<File>()
          .where((file) => file.path.endsWith('.dart'));

      var constructions = 0;
      for (final file in appFiles) {
        final source = await file.readAsString();
        constructions +=
            RegExp(r'\bAuthBloc\(\)').allMatches(source).length;
      }

      expect(constructions, 1);
    });

    test('unauthorized callback and widget tree use the same global AuthBloc',
        () async {
      final bootstrap = await File(
        'lib/app/bootstrap/app_bootstrap.dart',
      ).readAsString();
      final app = await File('lib/app/app.dart').readAsString();

      expect(
        bootstrap,
        contains('globalAuthBloc.add(const LogoutEvent())'),
      );
      expect(app, contains('final AuthBloc globalAuthBloc = AuthBloc();'));
      expect(
        app,
        contains('final resolvedAuthBloc = authBloc ?? globalAuthBloc;'),
      );
      expect(
        app,
        contains('BlocProvider<AuthBloc>.value'),
      );
      expect(app, contains('value: resolvedAuthBloc'));
      expect(app, contains('authBloc: resolvedAuthBloc'));
    });

    test('Sentry DSN and sampling semantics remain unchanged', () async {
      final source = await File(
        'lib/app/bootstrap/app_bootstrap.dart',
      ).readAsString();

      expect(source, contains("dotenv.env['SENTRY_DSN'] ?? ''"));
      expect(source, contains('options.dsn = sentryDsn'));
      expect(source, contains('options.tracesSampleRate = 0.1'));
      expect(source, contains('SentryFlutter.init'));
      expect(source, contains('appRunner: () => runApp(const MyApp())'));
      expect(
        source,
        contains("initializeDateFormatting('ar', null)"),
      );
      expect(
        source,
        contains('WidgetsFlutterBinding.ensureInitialized()'),
      );
    });

    test('Arabic locale, delegates, Splash and Dashboard provider remain',
        () async {
      final source = await File('lib/app/app.dart').readAsString();

      expect(
        source,
        contains('GlobalMaterialLocalizations.delegate'),
      );
      expect(
        source,
        contains('GlobalWidgetsLocalizations.delegate'),
      );
      expect(
        source,
        contains('GlobalCupertinoLocalizations.delegate'),
      );
      expect(source, contains("Locale('ar', '')"));
      expect(source, contains('home: const SplashScreen()'));
      expect(source, contains('BlocProvider<DashboardBloc>'));
      expect(source, contains("title: 'Wanasah App'"));
      expect(source, contains('debugShowCheckedModeBanner: false'));
    });

    test('login redirect preserves named-route duplicate guard and reset',
        () async {
      final source = await File(
        'lib/app/app_auth_navigation.dart',
      ).readAsString();

      expect(source, contains("route.settings.name == '/login'"));
      expect(source, contains('isAlreadyOnLogin = true'));
      expect(source, contains('pushAndRemoveUntil'));
      expect(
        source,
        contains("RouteSettings(name: '/login')"),
      );
      expect(source, contains('const LoginScreen()'));
      expect(source, contains('(route) => false'));
    });
  });

  group('Mechanical theme foundation', () {
    test('current theme and AppBar semantics are preserved', () {
      final theme = AppTheme.data;

      expect(AppTokens.primarySwatch, Colors.teal);
      expect(AppTokens.fontFamily, 'Cairo');
      expect(
        theme.scaffoldBackgroundColor,
        Colors.transparent,
      );
      expect(theme.canvasColor, Colors.white);
      expect(
        theme.visualDensity,
        VisualDensity.adaptivePlatformDensity,
      );

      final appBar = theme.appBarTheme;
      expect(appBar.backgroundColor, Colors.transparent);
      expect(appBar.elevation, 0);
      expect(appBar.centerTitle, isTrue);
      expect(appBar.iconTheme?.color, Colors.black87);
      expect(appBar.titleTextStyle?.color, Colors.black87);
      expect(appBar.titleTextStyle?.fontWeight, FontWeight.bold);
      expect(appBar.titleTextStyle?.fontSize, 18);
    });

    test('current background gradient values are exact', () {
      final gradient = AppTheme.backgroundGradient;

      expect(gradient.begin, Alignment.topLeft);
      expect(gradient.end, Alignment.bottomRight);
      expect(
        gradient.colors,
        const <Color>[
          Color.fromARGB(255, 194, 201, 173),
          Color.fromARGB(255, 117, 179, 97),
          Color.fromARGB(255, 255, 255, 255),
        ],
      );
      expect(gradient.stops, const <double>[0.0, 0.3, 0.8]);
    });

    test('SystemUiOverlayStyle remains visually equivalent', () {
      const style = AppSystemUi.overlayStyle;

      expect(style.statusBarColor, Colors.transparent);
      expect(style.statusBarIconBrightness, Brightness.dark);
      expect(style.systemNavigationBarColor, Colors.white);
      expect(
        style.systemNavigationBarIconBrightness,
        Brightness.dark,
      );
      expect(
        style.systemNavigationBarDividerColor,
        Colors.transparent,
      );
    });

    test('System UI boundary preserves SafeArea, Material and gradient',
        () async {
      final source = await File(
        'lib/app/theme/app_system_ui.dart',
      ).readAsString();

      expect(source, contains('AnnotatedRegion<SystemUiOverlayStyle>'));
      expect(source, contains('top: false'));
      expect(source, contains('bottom: true'));
      expect(source, contains('color: AppTokens.systemSurface'));
      expect(source, contains('gradient: AppTheme.backgroundGradient'));
    });
  });

  group('Architecture boundaries', () {
    test('app foundation does not absorb business feature code', () async {
      final appFiles = Directory('lib/app')
          .listSync(recursive: true)
          .whereType<File>()
          .where((file) => file.path.endsWith('.dart'));

      for (final file in appFiles) {
        final source = await file.readAsString();
        expect(
          source,
          isNot(contains('LocalDatabase')),
          reason: file.path,
        );
        expect(
          source,
          isNot(contains('SyncRepository')),
          reason: file.path,
        );
        expect(
          source,
          isNot(contains('VisitBloc')),
          reason: file.path,
        );
      }
    });

    test('main keeps MyApp compatibility export without owning composition',
        () async {
      final source = await File('lib/main.dart').readAsString();

      expect(source, contains("export 'app/app.dart' show MyApp;"));
      expect(source, isNot(contains('class MyApp')));
    });
  });
}
