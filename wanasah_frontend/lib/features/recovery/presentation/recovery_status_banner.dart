import 'package:flutter/material.dart';

import '../application/recovery_snapshot.dart';
import 'recovery_strings.dart';

class RecoveryStatusBanner extends StatelessWidget {
  const RecoveryStatusBanner({
    required this.snapshot,
    required this.readUnavailable,
    required this.onTap,
    super.key,
  });

  final RecoverySnapshot? snapshot;
  final bool readUnavailable;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();

    if (readUnavailable) {
      return _BannerSurface(
        icon: Icons.sync_problem,
        backgroundColor: Colors.orange.shade100,
        foregroundColor: Colors.deepOrange.shade900,
        text: recoveryString(
          RecoveryStringKey.readUnavailable,
          localeCode: locale,
        ),
      );
    }

    final value = snapshot;
    if (value == null || value.isEmpty) {
      return const SizedBox.shrink();
    }

    final String summary;
    if (value.hasBlocked && value.hasPending) {
      summary = recoveryString(
        RecoveryStringKey.combinedBanner,
        localeCode: locale,
        values: <String, Object>{
          'pending': value.pendingCount,
          'blocked': value.blockedCount,
        },
      );
    } else if (value.hasBlocked) {
      summary = recoveryString(
        RecoveryStringKey.blockedBanner,
        localeCode: locale,
        values: <String, Object>{'count': value.blockedCount},
      );
    } else {
      summary = recoveryString(
        RecoveryStringKey.pendingBanner,
        localeCode: locale,
        values: <String, Object>{'count': value.pendingCount},
      );
    }

    final blocked = value.hasBlocked;
    final background =
        blocked ? Colors.red.shade900 : Colors.orange.shade100;
    final foreground =
        blocked ? Colors.white : Colors.deepOrange.shade900;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: _BannerSurface(
        icon:
            blocked
                ? Icons.report_problem_outlined
                : Icons.sync_outlined,
        backgroundColor: background,
        foregroundColor: foreground,
        text:
            '$summary ${recoveryString(
              RecoveryStringKey.detailsHint,
              localeCode: locale,
            )}',
      ),
    );
  }
}

class _BannerSurface extends StatelessWidget {
  const _BannerSurface({
    required this.icon,
    required this.backgroundColor,
    required this.foregroundColor,
    required this.text,
  });

  final IconData icon;
  final Color backgroundColor;
  final Color foregroundColor;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(icon, color: foregroundColor, size: 28),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                color: foregroundColor,
                fontWeight: FontWeight.bold,
                fontSize: 14,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
