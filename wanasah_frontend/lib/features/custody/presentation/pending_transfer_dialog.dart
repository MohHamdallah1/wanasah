import 'package:flutter/material.dart';

import '../domain/pending_transfer.dart';
import '../domain/transfer_decision.dart';

enum PendingTransferDialogDisposition {
  empty,
  deferred,
  submitted,
}

class PendingTransferDialogResult {
  const PendingTransferDialogResult._(
    this.disposition,
    this.decisions,
  );

  const PendingTransferDialogResult.empty()
      : this._(
          PendingTransferDialogDisposition.empty,
          const <TransferDecision>[],
        );

  const PendingTransferDialogResult.deferred()
      : this._(
          PendingTransferDialogDisposition.deferred,
          const <TransferDecision>[],
        );

  PendingTransferDialogResult.submitted(
    List<TransferDecision> decisions,
  ) : this._(
          PendingTransferDialogDisposition.submitted,
          List<TransferDecision>.unmodifiable(decisions),
        );

  final PendingTransferDialogDisposition disposition;
  final List<TransferDecision> decisions;
}

Future<PendingTransferDialogResult> showPendingTransferDialog(
  BuildContext context,
  PendingTransferBatch batch,
) async {
  if (batch.items.isEmpty) {
    return const PendingTransferDialogResult.empty();
  }

  final responses = <int, TransferDecisionStatus>{};
  final reasonControllers = <int, TextEditingController>{
    for (final item in batch.items) item.transferId: TextEditingController(),
  };
  var submitLocked = false;

  try {
    final result = await showDialog<PendingTransferDialogResult>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return PopScope(
              canPop: false,
              child: AlertDialog(
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
                title: const Row(
                  children: [
                    Icon(Icons.inventory_2_outlined, color: Colors.blue),
                    SizedBox(width: 8),
                    Text(
                      'تحديث عهدة من الإدارة',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 18,
                      ),
                    ),
                  ],
                ),
                content: SizedBox(
                  width: double.maxFinite,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'راجع كل حركة وحدد قبولها أو رفضها. الرفض يتطلب سبباً واضحاً.',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Flexible(
                        child: ListView.builder(
                          shrinkWrap: true,
                          itemCount: batch.items.length,
                          itemBuilder: (context, index) {
                            final item = batch.items[index];
                            final response = responses[item.transferId];
                            final isAddition = item.deltaCartons > 0 ||
                                (item.deltaCartons == 0 &&
                                    item.deltaPacks > 0);

                            return Card(
                              color: isAddition
                                  ? Colors.green.shade50
                                  : Colors.red.shade50,
                              elevation: 0,
                              margin: const EdgeInsets.symmetric(vertical: 4),
                              child: Padding(
                                padding: const EdgeInsets.all(10),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.stretch,
                                  children: [
                                    Row(
                                      children: [
                                        Icon(
                                          isAddition
                                              ? Icons.add_circle
                                              : Icons.remove_circle,
                                          color: isAddition
                                              ? Colors.green
                                              : Colors.red,
                                        ),
                                        const SizedBox(width: 8),
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Text(
                                                item.productName,
                                                style: const TextStyle(
                                                  fontWeight: FontWeight.bold,
                                                ),
                                              ),
                                              Text(
                                                isAddition
                                                    ? 'إضافة للسيارة'
                                                    : 'سحب من السيارة',
                                                style: TextStyle(
                                                  color: isAddition
                                                      ? Colors.green[700]
                                                      : Colors.red[700],
                                                  fontWeight: FontWeight.bold,
                                                  fontSize: 12,
                                                ),
                                              ),
                                              Text(
                                                '${item.deltaCartons.abs()} كرتونة، '
                                                '${item.deltaPacks.abs()} حبة',
                                                style: const TextStyle(
                                                  fontSize: 12,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                        IconButton(
                                          tooltip: 'رفض',
                                          icon: Icon(
                                            Icons.close,
                                            color: response ==
                                                    TransferDecisionStatus.rejected
                                                ? Colors.red
                                                : Colors.grey,
                                          ),
                                          onPressed: () {
                                            setDialogState(() {
                                              responses[item.transferId] =
                                                  TransferDecisionStatus.rejected;
                                            });
                                          },
                                        ),
                                        IconButton(
                                          tooltip: 'قبول',
                                          icon: Icon(
                                            Icons.check,
                                            color: response ==
                                                    TransferDecisionStatus.accepted
                                                ? Colors.green
                                                : Colors.grey,
                                          ),
                                          onPressed: () {
                                            setDialogState(() {
                                              responses[item.transferId] =
                                                  TransferDecisionStatus.accepted;
                                              reasonControllers[item.transferId]
                                                  ?.clear();
                                            });
                                          },
                                        ),
                                      ],
                                    ),
                                    if (response ==
                                        TransferDecisionStatus.rejected) ...[
                                      const SizedBox(height: 8),
                                      TextField(
                                        controller:
                                            reasonControllers[item.transferId],
                                        maxLength: 1000,
                                        maxLines: 2,
                                        decoration: const InputDecoration(
                                          labelText: 'سبب الرفض',
                                          hintText:
                                              'مثال: الكمية الفعلية لا تطابق التحويل',
                                          border: OutlineInputBorder(),
                                        ),
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                    ],
                  ),
                ),
                actions: [
                  TextButton(
                    onPressed: () {
                      Navigator.pop(
                        dialogContext,
                        const PendingTransferDialogResult.deferred(),
                      );
                    },
                    child: const Text(
                      'تأجيل (إغلاق)',
                      style: TextStyle(color: Colors.grey),
                    ),
                  ),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.blue,
                    ),
                    onPressed: () {
                      if (responses.length != batch.items.length) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                              'يجب الرد على جميع الحركات بالقبول أو الرفض.',
                            ),
                            backgroundColor: Colors.red,
                          ),
                        );
                        return;
                      }

                      final decisions = <TransferDecision>[];
                      for (final item in batch.items) {
                        final status = responses[item.transferId]!;
                        final reason =
                            reasonControllers[item.transferId]?.text.trim();
                        if (status == TransferDecisionStatus.rejected &&
                            (reason == null || reason.isEmpty)) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text(
                                'سبب الرفض مطلوب لكل حركة مرفوضة.',
                              ),
                              backgroundColor: Colors.red,
                            ),
                          );
                          return;
                        }
                        decisions.add(
                          TransferDecision(
                            transferId: item.transferId,
                            status: status,
                            reason: reason,
                          ),
                        );
                      }

                      if (submitLocked) return;
                      submitLocked = true;
                      Navigator.pop(
                        dialogContext,
                        PendingTransferDialogResult.submitted(decisions),
                      );
                    },
                    child: const Text(
                      'إرسال الرد',
                      style: TextStyle(
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );

    return result ?? const PendingTransferDialogResult.deferred();
  } finally {
    for (final controller in reasonControllers.values) {
      controller.dispose();
    }
  }
}
