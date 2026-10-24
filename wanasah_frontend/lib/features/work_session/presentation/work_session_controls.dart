import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../l10n/generated/app_localizations.dart';
import '../application/work_session_action_issue.dart';
import 'work_session_issue_panel.dart';

class WorkSessionControls extends StatelessWidget {
  const WorkSessionControls({
    required this.isActiveSession,
    required this.activeSessionStartTime,
    required this.isOnBreak,
    required this.isActionInProgress,
    required this.onActionStarted,
    required this.onStart,
    required this.onEnd,
    required this.onToggleBreak,
    this.issue,
    super.key,
  });

  final bool isActiveSession;
  final String? activeSessionStartTime;
  final bool isOnBreak;
  final bool isActionInProgress;
  final VoidCallback onActionStarted;
  final VoidCallback onStart;
  final VoidCallback onEnd;
  final ValueChanged<String> onToggleBreak;
  final WorkSessionActionIssue? issue;

  DateTime? _startTime() {
    if (!isActiveSession || activeSessionStartTime == null) return null;
    return DateTime.tryParse(activeSessionStartTime!)?.toLocal();
  }

  Future<bool?> _showConfirmationDialog(
    BuildContext context, {
    required bool ending,
  }) {
    final l10n = AppLocalizations.of(context);
    return showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder:
          (dialogContext) => AlertDialog(
            title: Text(
              ending
                  ? l10n.workSessionConfirmEndTitle
                  : l10n.workSessionConfirmStartTitle,
            ),
            content: Text(
              ending
                  ? l10n.workSessionConfirmEndBody
                  : l10n.workSessionConfirmStartBody,
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(false),
                child: Text(l10n.cancel),
              ),
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(true),
                child: Text(l10n.confirm),
              ),
            ],
          ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final colors = Theme.of(context).colorScheme;
    final startTime = _startTime();
    final status =
        !isActiveSession
            ? l10n.workSessionReadyStatus
            : isOnBreak
            ? l10n.workSessionBreakStatus
            : l10n.workSessionActiveStatus;
    final title =
        !isActiveSession
            ? l10n.workSessionReadyTitle
            : isOnBreak
            ? l10n.workSessionBreakTitle
            : l10n.workSessionActiveTitle;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: colors.onSurface,
            borderRadius: BorderRadius.circular(24),
            boxShadow: [
              BoxShadow(
                color: colors.shadow.withValues(alpha: 0.12),
                blurRadius: 28,
                offset: const Offset(0, 12),
              ),
            ],
          ),
          child: DefaultTextStyle.merge(
            style: TextStyle(color: colors.surface),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    _StatusDot(active: isActiveSession, onBreak: isOnBreak),
                    const SizedBox(width: 8),
                    Text(
                      status,
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: colors.surface.withValues(alpha: 0.78),
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const Spacer(),
                    Icon(
                      isActiveSession
                          ? isOnBreak
                              ? Icons.free_breakfast_outlined
                              : Icons.route_rounded
                          : Icons.play_circle_outline_rounded,
                      color: colors.surface.withValues(alpha: 0.72),
                      size: 21,
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  title,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    color: colors.surface,
                    fontSize: 27,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.3,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  isActiveSession
                      ? isOnBreak
                          ? l10n.workSessionBreakHint
                          : l10n.workSessionActiveHint
                      : l10n.workSessionReadyHint,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: colors.surface.withValues(alpha: 0.66),
                  ),
                ),
                if (isActiveSession) ...[
                  const SizedBox(height: 14),
                  _SessionTiming(
                    startTime: startTime,
                    fallback: l10n.workSessionStartUnknown,
                  ),
                ],
                const SizedBox(height: 18),
                if (!isActiveSession)
                  FilledButton.icon(
                    key: const ValueKey('work-session-start'),
                    onPressed:
                        isActionInProgress
                            ? null
                            : () async {
                              final confirmed = await _showConfirmationDialog(
                                context,
                                ending: false,
                              );
                              if (!context.mounted || confirmed != true) return;
                              onActionStarted();
                              onStart();
                            },
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(52),
                      backgroundColor: colors.primary,
                      foregroundColor: colors.onPrimary,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                    ),
                    icon: const Icon(Icons.play_arrow_rounded),
                    label: Text(l10n.workSessionStartAction),
                  )
                else
                  Row(
                    children: [
                      Expanded(
                        flex: 6,
                        child: FilledButton.icon(
                          key: const ValueKey('work-session-break'),
                          onPressed:
                              isActionInProgress
                                  ? null
                                  : () {
                                    onActionStarted();
                                    onToggleBreak(isOnBreak ? 'end' : 'start');
                                  },
                          style: FilledButton.styleFrom(
                            minimumSize: const Size.fromHeight(52),
                            backgroundColor:
                                isOnBreak
                                    ? colors.tertiaryContainer
                                    : colors.primaryContainer,
                            foregroundColor:
                                isOnBreak
                                    ? colors.onTertiaryContainer
                                    : colors.onPrimaryContainer,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                          ),
                          icon: Icon(
                            isOnBreak
                                ? Icons.play_arrow_rounded
                                : Icons.free_breakfast_outlined,
                          ),
                          label: Text(
                            isOnBreak
                                ? l10n.workSessionEndBreakAction
                                : l10n.workSessionStartBreakAction,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        flex: 5,
                        child: OutlinedButton.icon(
                          key: const ValueKey('work-session-end'),
                          onPressed:
                              isActionInProgress
                                  ? null
                                  : () async {
                                    final confirmed =
                                        await _showConfirmationDialog(
                                          context,
                                          ending: true,
                                        );
                                    if (!context.mounted || confirmed != true) {
                                      return;
                                    }
                                    onActionStarted();
                                    onEnd();
                                  },
                          style: OutlinedButton.styleFrom(
                            minimumSize: const Size.fromHeight(52),
                            foregroundColor: colors.errorContainer,
                            side: BorderSide(
                              color: colors.errorContainer.withValues(
                                alpha: 0.58,
                              ),
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                          ),
                          icon: const Icon(Icons.stop_circle_outlined),
                          label: Text(l10n.workSessionEndAction),
                        ),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ),
        if (issue != null) WorkSessionIssuePanel(issue: issue!),
      ],
    );
  }
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.active, required this.onBreak});

  final bool active;
  final bool onBreak;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final color =
        !active
            ? colors.surface.withValues(alpha: 0.48)
            : onBreak
            ? colors.tertiaryContainer
            : const Color(0xFF63E6BE);
    return Container(
      width: 9,
      height: 9,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        boxShadow:
            active
                ? [
                  BoxShadow(
                    color: color.withValues(alpha: 0.38),
                    blurRadius: 8,
                    spreadRadius: 1,
                  ),
                ]
                : null,
      ),
    );
  }
}

class _SessionTiming extends StatelessWidget {
  const _SessionTiming({required this.startTime, required this.fallback});

  final DateTime? startTime;
  final String fallback;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final l10n = AppLocalizations.of(context);
    final locale = Localizations.localeOf(context).toLanguageTag();
    final resolved = startTime;
    if (resolved == null) {
      return Text(
        fallback,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
          color: colors.surface.withValues(alpha: 0.72),
        ),
      );
    }

    final formatted = _westernDigits(DateFormat.Hm(locale).format(resolved));
    return StreamBuilder<DateTime>(
      stream: Stream<DateTime>.periodic(
        const Duration(seconds: 30),
        (_) => DateTime.now(),
      ),
      initialData: DateTime.now(),
      builder: (context, snapshot) {
        final now = snapshot.data ?? DateTime.now();
        final duration =
            now.isBefore(resolved) ? Duration.zero : now.difference(resolved);
        return Wrap(
          spacing: 12,
          runSpacing: 7,
          children: [
            _TimingChip(
              icon: Icons.schedule_outlined,
              text: l10n.workSessionStartedAt(formatted),
            ),
            _TimingChip(
              icon: Icons.timelapse_rounded,
              text: l10n.workSessionElapsed(_duration(duration)),
            ),
          ],
        );
      },
    );
  }

  static String _duration(Duration value) {
    final hours = value.inHours;
    final minutes = value.inMinutes.remainder(60);
    return '${hours.toString().padLeft(2, '0')}:${minutes.toString().padLeft(2, '0')}';
  }

  static String _westernDigits(String value) => value.replaceAllMapped(
    RegExp('[٠-٩]'),
    (match) => (match[0]!.codeUnitAt(0) - 0x0660).toString(),
  );
}

class _TimingChip extends StatelessWidget {
  const _TimingChip({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.075),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: colors.surface.withValues(alpha: 0.10)),
      ),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(10, 6, 11, 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: colors.surface.withValues(alpha: 0.72)),
            const SizedBox(width: 6),
            Text(
              text,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: colors.surface.withValues(alpha: 0.80),
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
