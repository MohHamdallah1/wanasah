import 'package:flutter/material.dart';

import '../domain/pending_transfer.dart';
import '../domain/transfer_decision.dart';
import 'pending_transfer_quantity_formatter.dart';
import 'pending_transfer_strings.dart';

enum PendingTransferDialogDisposition { empty, deferred, submitted }

class PendingTransferDialogResult {
  const PendingTransferDialogResult._(this.disposition, this.decisions);

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

  PendingTransferDialogResult.submitted(List<TransferDecision> decisions)
    : this._(
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
  final strings = PendingTransferStrings.of(context);
  final locale = Localizations.localeOf(context).toString();

  final responses = <int, TransferDecisionStatus>{};
  final reasonControllers = <int, TextEditingController>{
    for (final item in batch.items) item.transferId: TextEditingController(),
  };
  var submitLocked = false;
  ModalRoute<PendingTransferDialogResult>? dialogRoute;

  try {
    final result = await showDialog<PendingTransferDialogResult>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        dialogRoute = ModalRoute.of<PendingTransferDialogResult>(dialogContext);
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return PopScope(
              canPop: false,
              child: AlertDialog(
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
                title: Row(
                  children: [
                    const Icon(Icons.inventory_2_outlined, color: Colors.blue),
                    const SizedBox(width: 8),
                    Text(
                      strings.t('title'),
                      style: const TextStyle(
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
                      Text(
                        strings.t('instructions'),
                        style: const TextStyle(
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
                            final isAddition = item.isAddition;

                            return Card(
                              color:
                                  isAddition
                                      ? Colors.green.shade50
                                      : Colors.red.shade50,
                              elevation: 0,
                              margin: const EdgeInsets.symmetric(vertical: 4),
                              child: Padding(
                                padding: const EdgeInsets.all(10),
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.stretch,
                                  children: [
                                    Row(
                                      children: [
                                        Icon(
                                          isAddition
                                              ? Icons.add_circle
                                              : Icons.remove_circle,
                                          color:
                                              isAddition
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
                                                    ? strings.t('add')
                                                    : strings.t('remove'),
                                                style: TextStyle(
                                                  color:
                                                      isAddition
                                                          ? Colors.green[700]
                                                          : Colors.red[700],
                                                  fontWeight: FontWeight.bold,
                                                  fontSize: 12,
                                                ),
                                              ),
                                              Text(
                                                formatPendingTransferQuantity(
                                                  item,
                                                  locale: locale,
                                                ),
                                                style: const TextStyle(
                                                  fontSize: 12,
                                                ),
                                              ),
                                            ],
                                          ),
                                        ),
                                        IconButton(
                                          tooltip: strings.t('reject'),
                                          icon: Icon(
                                            Icons.close,
                                            color:
                                                response ==
                                                        TransferDecisionStatus
                                                            .rejected
                                                    ? Colors.red
                                                    : Colors.grey,
                                          ),
                                          onPressed: () {
                                            setDialogState(() {
                                              responses[item.transferId] =
                                                  TransferDecisionStatus
                                                      .rejected;
                                            });
                                          },
                                        ),
                                        IconButton(
                                          tooltip: strings.t('accept'),
                                          icon: Icon(
                                            Icons.check,
                                            color:
                                                response ==
                                                        TransferDecisionStatus
                                                            .accepted
                                                    ? Colors.green
                                                    : Colors.grey,
                                          ),
                                          onPressed: () {
                                            setDialogState(() {
                                              responses[item.transferId] =
                                                  TransferDecisionStatus
                                                      .accepted;
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
                                        decoration: InputDecoration(
                                          labelText: strings.t('reason'),
                                          hintText: strings.t('reasonHint'),
                                          border: const OutlineInputBorder(),
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
                    child: Text(
                      strings.t('defer'),
                      style: const TextStyle(color: Colors.grey),
                    ),
                  ),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.blue,
                    ),
                    onPressed: () {
                      if (responses.length != batch.items.length) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text(strings.t('allRequired')),
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
                            SnackBar(
                              content: Text(strings.t('reasonRequired')),
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
                    child: Text(
                      strings.t('submit'),
                      style: const TextStyle(
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
    // A popped dialog still owns its fields until the exit transition finishes.
    await dialogRoute?.completed;
    for (final controller in reasonControllers.values) {
      controller.dispose();
    }
  }
}
