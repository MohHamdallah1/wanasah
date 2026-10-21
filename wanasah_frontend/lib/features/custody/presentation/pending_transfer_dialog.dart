import 'package:flutter/material.dart';

enum PendingTransferDialogDisposition {
  empty,
  deferred,
  submitted,
}

class PendingTransferDialogResult {
  const PendingTransferDialogResult._(
    this.disposition,
    this.detailedResponses,
  );

  const PendingTransferDialogResult.empty()
    : this._(
        PendingTransferDialogDisposition.empty,
        const <Map<String, dynamic>>[],
      );

  const PendingTransferDialogResult.deferred()
    : this._(
        PendingTransferDialogDisposition.deferred,
        const <Map<String, dynamic>>[],
      );

  PendingTransferDialogResult.submitted(
    List<Map<String, dynamic>> detailedResponses,
  ) : this._(
        PendingTransferDialogDisposition.submitted,
        detailedResponses,
      );

  final PendingTransferDialogDisposition disposition;
  final List<Map<String, dynamic>> detailedResponses;
}

Future<PendingTransferDialogResult> showPendingTransferDialog(
  BuildContext context,
  Map<String, dynamic> batchData,
) async {
  final List<dynamic> items = batchData['items'] ?? [];
  final validItemsCount =
      items.where((item) {
        final id =
            int.tryParse(
              item['real_transfer_id']?.toString() ?? '',
            ) ??
            0;
        return id != 0;
      }).length;

  if (items.isEmpty || validItemsCount == 0) {
    return const PendingTransferDialogResult.empty();
  }

  final Map<int, String> itemResponses = {};
  bool submitLocked = false;

  final result = await showDialog<PendingTransferDialogResult>(
    context: context,
    barrierDismissible: false,
    builder: (dialogContext) {
      return PopScope(
        canPop: false,
        child: AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          title: const Row(
            children: [
              Icon(
                Icons.inventory_2_outlined,
                color: Colors.blue,
              ),
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
                  'قامت الإدارة بإجراء التعديلات التالية على عهدتك. هل توافق؟',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 10),
                Flexible(
                  child: ListView.builder(
                    shrinkWrap: true,
                    itemCount: items.length,
                    itemBuilder: (context, index) {
                      final item = items[index];
                      final String productName =
                          item['product_name'] ?? 'غير معروف';

                      final rawCartons =
                          int.tryParse(
                            item['delta_cartons']?.toString() ?? '',
                          ) ??
                          0;
                      final rawPacks =
                          int.tryParse(
                            item['delta_packs']?.toString() ?? '',
                          ) ??
                          0;
                      final isAddition =
                          rawCartons > 0 ||
                          (rawCartons == 0 && rawPacks > 0);

                      final absCartons = rawCartons.abs();
                      final absPacks = rawPacks.abs();

                      return Card(
                        color:
                            isAddition
                                ? Colors.green.shade50
                                : Colors.red.shade50,
                        elevation: 0,
                        margin: const EdgeInsets.symmetric(
                          vertical: 4,
                        ),
                        child: ListTile(
                          dense: true,
                          leading: Icon(
                            isAddition
                                ? Icons.add_circle
                                : Icons.remove_circle,
                            color:
                                isAddition
                                    ? Colors.green
                                    : Colors.red,
                          ),
                          title: Text(
                            productName,
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          subtitle: Text(
                            isAddition
                                ? 'إضافة للسيارة'
                                : 'سحب من السيارة',
                            style: TextStyle(
                              color:
                                  isAddition
                                      ? Colors.green[700]
                                      : Colors.red[700],
                              fontWeight: FontWeight.bold,
                              fontSize: 12,
                            ),
                          ),
                          trailing: StatefulBuilder(
                            builder: (context, setState) {
                              final itemId =
                                  int.tryParse(
                                    item['real_transfer_id']
                                            ?.toString() ??
                                        '',
                                  ) ??
                                  0;
                              if (itemId == 0) {
                                return const SizedBox.shrink();
                              }
                              final currentResponse =
                                  itemResponses[itemId];

                              return ConstrainedBox(
                                constraints: const BoxConstraints(
                                  maxWidth: 150,
                                ),
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  mainAxisAlignment:
                                      MainAxisAlignment.end,
                                  children: [
                                    Expanded(
                                      child: Text(
                                        '$absCartons كرتونة\n$absPacks حبة',
                                        textAlign: TextAlign.center,
                                        softWrap: false,
                                        overflow:
                                            TextOverflow.visible,
                                        style: const TextStyle(
                                          fontSize: 12,
                                          fontWeight:
                                              FontWeight.bold,
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 4),
                                    IconButton(
                                      padding: EdgeInsets.zero,
                                      constraints:
                                          const BoxConstraints(),
                                      icon: Icon(
                                        Icons.close,
                                        color:
                                            currentResponse ==
                                                    'rejected'
                                                ? Colors.red
                                                : Colors.grey,
                                      ),
                                      onPressed:
                                          () => setState(
                                            () =>
                                                itemResponses[itemId] =
                                                    'rejected',
                                          ),
                                    ),
                                    const SizedBox(width: 4),
                                    IconButton(
                                      padding: EdgeInsets.zero,
                                      constraints:
                                          const BoxConstraints(),
                                      icon: Icon(
                                        Icons.check,
                                        color:
                                            currentResponse ==
                                                    'accepted'
                                                ? Colors.green
                                                : Colors.grey,
                                      ),
                                      onPressed:
                                          () => setState(
                                            () =>
                                                itemResponses[itemId] =
                                                    'accepted',
                                          ),
                                    ),
                                  ],
                                ),
                              );
                            },
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
                final uniqueValidIds =
                    items
                        .map(
                          (i) =>
                              int.tryParse(
                                i['real_transfer_id']
                                        ?.toString() ??
                                    '',
                              ) ??
                              0,
                        )
                        .where((id) => id != 0)
                        .toSet();

                if (itemResponses.length !=
                    uniqueValidIds.length) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'يجب الرد على جميع الأصناف بالقبول أو الرفض',
                      ),
                      backgroundColor: Colors.red,
                    ),
                  );
                  return;
                }

                if (submitLocked) return;
                submitLocked = true;

                final detailedResponses =
                    itemResponses.entries
                        .map(
                          (entry) => <String, dynamic>{
                            'transfer_id': entry.key,
                            'status': entry.value,
                          },
                        )
                        .toList();

                Navigator.pop(
                  dialogContext,
                  PendingTransferDialogResult.submitted(
                    detailedResponses,
                  ),
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

  return result ?? const PendingTransferDialogResult.deferred();
}
