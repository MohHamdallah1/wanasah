import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/sync/durable_command.dart';
import '../application/recovery_command.dart';
import '../application/recovery_snapshot.dart';
import 'recovery_strings.dart';

Future<void> showRecoveryPanel(
  BuildContext context,
  RecoverySnapshot snapshot,
) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: Colors.white,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (context) => RecoveryPanel(snapshot: snapshot),
  );
}

class RecoveryPanel extends StatelessWidget {
  const RecoveryPanel({
    required this.snapshot,
    super.key,
  });

  final RecoverySnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(context).height * 0.78,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.shield_outlined,
                color: Colors.orange,
                size: 44,
              ),
              const SizedBox(height: 8),
              Text(
                recoveryString(
                  RecoveryStringKey.panelTitle,
                  localeCode: locale,
                ),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 6),
              Text(
                recoveryString(
                  RecoveryStringKey.panelDescription,
                  localeCode: locale,
                ),
                textAlign: TextAlign.center,
              ),
              if (snapshot.hasBlocked) ...[
                const SizedBox(height: 6),
                Text(
                  recoveryString(
                    RecoveryStringKey.readOnlyNotice,
                    localeCode: locale,
                  ),
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Colors.red.shade800,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
              const SizedBox(height: 12),
              if (snapshot.isEmpty)
                Text(
                  recoveryString(
                    RecoveryStringKey.noRecoveryItems,
                    localeCode: locale,
                  ),
                )
              else
                Flexible(
                  child: ListView(
                    shrinkWrap: true,
                    children: [
                      if (snapshot.pending.isNotEmpty) ...[
                        _SectionTitle(
                          text: recoveryString(
                            RecoveryStringKey.pendingSection,
                            localeCode: locale,
                          ),
                        ),
                        ...snapshot.pending.map(
                          (command) => _RecoveryCommandCard(
                            command: command,
                            localeCode: locale,
                          ),
                        ),
                      ],
                      if (snapshot.blocked.isNotEmpty) ...[
                        _SectionTitle(
                          text: recoveryString(
                            RecoveryStringKey.blockedSection,
                            localeCode: locale,
                          ),
                        ),
                        ...snapshot.blocked.map(
                          (command) => _RecoveryCommandCard(
                            command: command,
                            localeCode: locale,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 4),
      child: Align(
        alignment: AlignmentDirectional.centerStart,
        child: Text(
          text,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
      ),
    );
  }
}

class _RecoveryCommandCard extends StatelessWidget {
  const _RecoveryCommandCard({
    required this.command,
    required this.localeCode,
  });

  final RecoveryCommand command;
  final String localeCode;

  @override
  Widget build(BuildContext context) {
    final blocked = command.isBlocked;
    final missing = recoveryString(
      RecoveryStringKey.missingValue,
      localeCode: localeCode,
    );

    final details = <String>[
      _line(
        RecoveryStringKey.operationLabel,
        _operationLabel(command.normalizedType),
      ),
      blocked
          ? recoveryString(
              RecoveryStringKey.blockedState,
              localeCode: localeCode,
            )
          : recoveryString(
              RecoveryStringKey.pendingState,
              localeCode: localeCode,
            ),
      _line(
        RecoveryStringKey.commandIdLabel,
        command.commandId ?? missing,
      ),
      _line(
        RecoveryStringKey.localRecordLabel,
        command.recordId.toString(),
      ),
      _line(
        RecoveryStringKey.attemptsLabel,
        command.attemptCount.toString(),
      ),
      _line(
        RecoveryStringKey.createdAtLabel,
        _formatDate(command.createdAt, missing),
      ),
      if (command.visitId != null)
        _line(
          RecoveryStringKey.visitLabel,
          command.visitId.toString(),
        ),
      if (command.transferId != null)
        _line(
          RecoveryStringKey.transferLabel,
          command.transferId.toString(),
        ),
      if (command.referenceLabel != null)
        _line(
          RecoveryStringKey.referenceLabel,
          command.referenceLabel!,
        ),
      if (blocked || command.lastErrorCode != null)
        _line(
          RecoveryStringKey.errorCodeLabel,
          command.lastErrorCode ?? missing,
        ),
      if (command.lastRequestId != null)
        _line(
          RecoveryStringKey.requestIdLabel,
          command.lastRequestId!,
        ),
      if (command.displayFallback != null)
        _line(
          RecoveryStringKey.reasonLabel,
          command.displayFallback!,
        ),
    ];

    return Card(
      child: ListTile(
        leading: Icon(
          blocked ? Icons.lock_outline : Icons.schedule_outlined,
          color: blocked ? Colors.red.shade800 : Colors.orange.shade800,
        ),
        title: Text(
          _operationLabel(command.normalizedType),
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: Text(details.join('\n')),
      ),
    );
  }

  String _line(
    RecoveryStringKey label,
    String value,
  ) {
    return '${recoveryString(label, localeCode: localeCode)}: $value';
  }

  String _operationLabel(String type) {
    final key = switch (type) {
      DurableCommandType.submitSale => RecoveryStringKey.submitSale,
      DurableCommandType.transferResponse =>
        RecoveryStringKey.transferResponse,
      DurableCommandType.legacyToggleBreak =>
        RecoveryStringKey.legacyBreak,
      DurableCommandType.corrupt => RecoveryStringKey.corrupt,
      _ => RecoveryStringKey.unknownOperation,
    };
    return recoveryString(key, localeCode: localeCode);
  }

  String _formatDate(DateTime? value, String missing) {
    if (value == null) return missing;
    return DateFormat.yMd(localeCode)
        .add_Hm()
        .format(value.toLocal());
  }
}
