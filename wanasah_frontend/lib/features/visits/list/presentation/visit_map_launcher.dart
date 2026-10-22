import 'package:map_launcher/map_launcher.dart';
import 'package:url_launcher/url_launcher.dart';

import '../application/visit_list_read_model.dart';
import '../application/visit_map_target.dart';

enum VisitMapLaunchOutcome {
  opened,
  noLocation,
  noMapApplication,
  invalidLink,
  failed,
}

class VisitMapLauncher {
  const VisitMapLauncher();

  Future<VisitMapLaunchOutcome> open(VisitListRow row) async {
    try {
      final target = VisitMapTarget.fromRow(row);

      if (target.hasCoordinates) {
        final installed = await MapLauncher.installedMaps;
        if (installed.isNotEmpty) {
          final google = installed.where(
            (map) => map.mapType == MapType.google,
          );
          final selected =
              google.isNotEmpty ? google.first : installed.first;
          await selected.showMarker(
            coords: Coords(
              target.latitude!,
              target.longitude!,
            ),
            title: row.shopName,
          );
          return VisitMapLaunchOutcome.opened;
        }

        if (target.fallbackUri != null) {
          return _openUri(target.fallbackUri!);
        }
        return target.hasInvalidRawLink
            ? VisitMapLaunchOutcome.invalidLink
            : VisitMapLaunchOutcome.noMapApplication;
      }

      if (target.fallbackUri != null) {
        return _openUri(target.fallbackUri!);
      }
      if (target.hasInvalidRawLink) {
        return VisitMapLaunchOutcome.invalidLink;
      }
      return VisitMapLaunchOutcome.noLocation;
    } catch (_) {
      return VisitMapLaunchOutcome.failed;
    }
  }

  Future<VisitMapLaunchOutcome> _openUri(Uri uri) async {
    final launched = await launchUrl(
      uri,
      mode: LaunchMode.externalApplication,
    );
    return launched
        ? VisitMapLaunchOutcome.opened
        : VisitMapLaunchOutcome.failed;
  }
}
