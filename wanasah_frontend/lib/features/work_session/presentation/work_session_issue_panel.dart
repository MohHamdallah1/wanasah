import 'package:flutter/material.dart';

import '../application/work_session_action_issue.dart';
import 'work_session_issue_message.dart';

class WorkSessionIssuePanel extends StatelessWidget {
  const WorkSessionIssuePanel({required this.issue, super.key});

  final WorkSessionActionIssue issue;

  @override
  Widget build(BuildContext context) {
    final unresolved = issue.kind == WorkSessionActionIssueKind.unresolved;

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: unresolved ? Colors.orange.shade50 : Colors.red.shade50,
        border: Border.all(
          color: unresolved ? Colors.orange.shade300 : Colors.red.shade200,
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            unresolved ? Icons.sync_problem : Icons.info_outline,
            color: unresolved ? Colors.orange.shade800 : Colors.red.shade700,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              workSessionIssueMessage(
                issue,
                localeCode: Localizations.localeOf(context).toLanguageTag(),
              ),
              style: const TextStyle(height: 1.45),
            ),
          ),
        ],
      ),
    );
  }
}
