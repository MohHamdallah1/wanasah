import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import '../../blocs/auth/auth_event.dart';
import '../../core/network/api_client.dart';
import '../app.dart';
import 'app_environment.dart';
import 'app_error_handlers.dart';

class AppBootstrap {
  AppBootstrap({
    AppEnvironmentLoader? environmentLoader,
  }) : _environmentLoader =
           environmentLoader ?? AppEnvironmentLoader();

  final AppEnvironmentLoader _environmentLoader;

  Future<void> run() async {
    WidgetsFlutterBinding.ensureInitialized();
    AppErrorHandlers.install();

    await initializeDateFormatting('ar', null);
    await _environmentLoader.load();

    ApiClient.init(
      onUnauthorized: () {
        globalAuthBloc.add(const LogoutEvent());
      },
    );

    final sentryDsn = dotenv.env['SENTRY_DSN'] ?? '';
    if (sentryDsn.isEmpty) {
      debugPrint(
        '⚠️ WARNING: SENTRY_DSN is empty. '
        'Sentry crash tracking is DISABLED.',
      );
    }

    await SentryFlutter.init(
      (options) {
        options.dsn = sentryDsn;
        options.tracesSampleRate = 0.1;
      },
      appRunner: () => runApp(const MyApp()),
    );
  }
}
