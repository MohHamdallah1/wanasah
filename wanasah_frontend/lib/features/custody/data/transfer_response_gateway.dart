import 'package:wanasah_frontend/repositories/sync_repository.dart';

import '../domain/transfer_decision.dart';

enum TransferDispatchDisposition {
  live,
  queued,
}

class TransferDispatchResult {
  const TransferDispatchResult({
    required this.decision,
    required this.disposition,
  });

  final TransferDecision decision;
  final TransferDispatchDisposition disposition;
}

class CustodyTransferGateway {
  CustodyTransferGateway({SyncRepository? syncRepository})
      : _syncRepository = syncRepository ?? SyncRepository();

  final SyncRepository _syncRepository;

  Future<TransferDispatchResult> respond(TransferDecision decision) async {
    final sentLive = await _syncRepository.respondToTransfer(
      transferId: decision.transferId,
      responseStr: decision.status.wireValue,
      reason: decision.reason,
    );
    return TransferDispatchResult(
      decision: decision,
      disposition: sentLive
          ? TransferDispatchDisposition.live
          : TransferDispatchDisposition.queued,
    );
  }
}
