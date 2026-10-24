class WorkSessionSnapshot {
  const WorkSessionSnapshot({
    required this.isActive,
    required this.sessionId,
    required this.startTime,
    required this.isOnBreak,
  });

  const WorkSessionSnapshot.inactive()
    : isActive = false,
      sessionId = null,
      startTime = null,
      isOnBreak = false;

  final bool isActive;
  final int? sessionId;
  final String? startTime;

  /// Null means the endpoint does not expose break state.
  final bool? isOnBreak;

  factory WorkSessionSnapshot.fromActiveResponse(dynamic data) {
    final root = _stringKeyedMap(data);
    if (root == null || root['active_session_found'] is! bool) {
      throw const FormatException('Invalid active-session response.');
    }

    final found = root['active_session_found'] as bool;
    if (!found) return const WorkSessionSnapshot.inactive();

    final sessionId = int.tryParse(root['session_id']?.toString() ?? '');
    if (sessionId == null || sessionId <= 0) {
      throw const FormatException('Active session is missing a valid id.');
    }

    return WorkSessionSnapshot(
      isActive: true,
      sessionId: sessionId,
      startTime: _nonEmptyString(root['start_time']),
      isOnBreak: null,
    );
  }

  factory WorkSessionSnapshot.fromDashboardResponse(dynamic data) {
    final root = _stringKeyedMap(data);
    if (root == null) {
      throw const FormatException('Invalid dashboard response.');
    }

    final rawSession = root['active_session'];
    if (rawSession == null) {
      return const WorkSessionSnapshot.inactive();
    }

    final session = _stringKeyedMap(rawSession);
    if (session == null) {
      throw const FormatException('Invalid dashboard session response.');
    }

    final rawSessionId = session['session_id'];
    if (rawSessionId == null) {
      final startTime = _nonEmptyString(session['start_time']);
      final authorizedToSell = session['is_authorized_to_sell'];

      // Dashboard intentionally reuses the active_session envelope before a
      // Work Session starts so Route vehicle inventory can remain visible.
      // This exact shape means "route assigned, session inactive".
      if (startTime == null && authorizedToSell == false) {
        return const WorkSessionSnapshot.inactive();
      }

      throw const FormatException('Dashboard session is missing a valid id.');
    }

    final sessionId = int.tryParse(rawSessionId.toString());
    if (sessionId == null || sessionId <= 0) {
      throw const FormatException('Dashboard session is missing a valid id.');
    }

    return WorkSessionSnapshot(
      isActive: true,
      sessionId: sessionId,
      startTime: _nonEmptyString(session['start_time']),
      isOnBreak:
          session['break_start_time'] != null &&
          session['break_end_time'] == null,
    );
  }

  static Map<String, dynamic>? _stringKeyedMap(dynamic value) {
    if (value is! Map) return null;
    return <String, dynamic>{
      for (final entry in value.entries)
        if (entry.key is String) entry.key as String: entry.value,
    };
  }

  static String? _nonEmptyString(dynamic value) {
    if (value is! String) return null;
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }
}
