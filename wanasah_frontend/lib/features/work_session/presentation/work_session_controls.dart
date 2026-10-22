import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

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

  String _formattedStartTime() {
    if (!isActiveSession || activeSessionStartTime == null) {
      return '';
    }

    try {
      final startTime = DateTime.parse(activeSessionStartTime!).toLocal();
      return DateFormat('hh:mm a').format(startTime);
    } catch (_) {
      return 'غير معروف';
    }
  }

  Future<bool?> _showConfirmationDialog(
    BuildContext context,
    String title,
    String content,
  ) {
    return showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return AlertDialog(
          title: Text(title),
          content: Text(content),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('إلغاء'),
            ),
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('نعم، تأكيد'),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final startTimeFormatted = _formattedStartTime();

    return Column(
      children: [
        Center(
          child: Text(
            isActiveSession
                ? 'جاري العمـل (بدأ الساعة: $startTimeFormatted)'
                : 'اضغط لبدء العمل',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.bold,
              color:
                  isActiveSession ? Colors.green[700] : Colors.red[700],
            ),
          ),
        ),
        const SizedBox(height: 15),
        Center(
          child: ElevatedButton.icon(
            icon: Icon(
              isActiveSession
                  ? Icons.stop_circle_outlined
                  : Icons.play_arrow,
            ),
            label: Text(
              isActiveSession ? 'إنهاء العمل' : 'بدء العمل',
            ),
            onPressed:
                isActionInProgress
                    ? null
                    : () async {
                      if (isActiveSession && isOnBreak) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('يجب إنهاء الاستراحة أولاً!'),
                            backgroundColor: Colors.orange,
                          ),
                        );
                        return;
                      }

                      final confirmed = await _showConfirmationDialog(
                        context,
                        isActiveSession ? 'إنهاء العمل؟' : 'بدء العمل؟',
                        isActiveSession
                            ? 'هل تريد إنهاء جلسة العمل الحالية؟'
                            : 'هل تريد بدء جلسة عمل جديدة؟',
                      );

                      if (!context.mounted) return;
                      if (confirmed == true) {
                        onActionStarted();
                        if (isActiveSession) {
                          onEnd();
                        } else {
                          onStart();
                        }
                      }
                    },
            style: ElevatedButton.styleFrom(
              backgroundColor:
                  isActiveSession ? Colors.red[600] : Colors.green[600],
              padding: const EdgeInsets.symmetric(
                horizontal: 30,
                vertical: 12,
              ),
              textStyle: const TextStyle(fontSize: 16),
            ),
          ),
        ),
        if (isActiveSession) ...[
          const SizedBox(height: 10),
          Center(
            child: ElevatedButton.icon(
              onPressed:
                  isActionInProgress
                      ? null
                      : () {
                        onActionStarted();
                        onToggleBreak(isOnBreak ? 'end' : 'start');
                      },
              icon: Icon(
                isOnBreak
                    ? Icons.free_breakfast_outlined
                    : Icons.free_breakfast,
              ),
              label: Text(
                isOnBreak ? 'إنهاء الاستراحة' : 'بدء الاستراحة',
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor:
                    isOnBreak ? Colors.orange[700] : Colors.blue[600],
                padding: const EdgeInsets.symmetric(
                  horizontal: 30,
                  vertical: 12,
                ),
                textStyle: const TextStyle(fontSize: 16),
              ),
            ),
          ),
        ],
      ],
    );
  }
}
