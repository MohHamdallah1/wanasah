import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

typedef EnvironmentFileLoader = Future<void> Function();
typedef BootstrapLogSink = void Function(String message);

class AppEnvironmentLoader {
  AppEnvironmentLoader({
    bool isReleaseMode = kReleaseMode,
    EnvironmentFileLoader? fileLoader,
    BootstrapLogSink? logSink,
  }) : _isReleaseMode = isReleaseMode,
       _fileLoader = fileLoader ?? _loadDefaultEnvironment,
       _logSink = logSink ?? ((message) => debugPrint(message));

  final bool _isReleaseMode;
  final EnvironmentFileLoader _fileLoader;
  final BootstrapLogSink _logSink;

  Future<void> load() async {
    try {
      await _fileLoader();
    } catch (_) {
      if (_isReleaseMode) {
        throw Exception(
          'CRITICAL ERROR: .env file is missing in Release mode! '
          'Application cannot start safely.',
        );
      }

      _logSink(
        '⚠️ تنبيه: ملف .env غير موجود. '
        'سيتم استخدام الروابط الافتراضية للتطوير.',
      );
    }
  }

  static Future<void> _loadDefaultEnvironment() {
    return dotenv.load(fileName: '.env');
  }
}
