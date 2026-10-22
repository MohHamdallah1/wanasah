import 'visit_list_read_model.dart';

class VisitMapTarget {
  const VisitMapTarget({
    required this.latitude,
    required this.longitude,
    required this.fallbackUri,
    required this.hasInvalidRawLink,
  });

  final double? latitude;
  final double? longitude;
  final Uri? fallbackUri;
  final bool hasInvalidRawLink;

  bool get hasCoordinates => latitude != null && longitude != null;

  factory VisitMapTarget.fromRow(VisitListRow row) {
    final lat = row.visit.latitude;
    final lng = row.visit.longitude;
    final coordinatesValid = _validCoordinates(lat, lng);

    final rawLink = row.visit.locationLink?.trim() ?? '';
    final fallbackUri = _safeHttpUri(rawLink);

    return VisitMapTarget(
      latitude: coordinatesValid ? lat : null,
      longitude: coordinatesValid ? lng : null,
      fallbackUri: fallbackUri,
      hasInvalidRawLink: rawLink.isNotEmpty && fallbackUri == null,
    );
  }

  static bool _validCoordinates(double? lat, double? lng) {
    if (lat == null || lng == null) return false;
    if (!lat.isFinite || !lng.isFinite) return false;
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      return false;
    }
    return !(lat == 0.0 && lng == 0.0);
  }

  static Uri? _safeHttpUri(String raw) {
    if (raw.isEmpty) return null;

    final parsedRaw = Uri.tryParse(raw);
    if (parsedRaw?.hasScheme == true) {
      if (parsedRaw!.scheme != 'http' && parsedRaw.scheme != 'https') {
        return null;
      }
    }

    final candidate =
        parsedRaw?.hasScheme == true
            ? raw
            : (raw.startsWith('//') ? 'https:$raw' : 'https://$raw');
    final uri = Uri.tryParse(candidate);
    if (uri == null ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.trim().isEmpty) {
      return null;
    }
    return uri;
  }
}
