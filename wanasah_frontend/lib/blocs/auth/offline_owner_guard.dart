import '../../core/sync/durable_command.dart';
import '../../core/sync/durable_command_owner.dart';

enum OfflineOwnerLoginDecision {
  sameOwner,
  differentDriverSameCompany,
  differentCompany,
  noOwner,
}

enum OfflineOwnerLoginOutcome {
  allowNoPendingOwner,
  allowSameOwner,
  allowStaleOwner,
  blockDifferentDriverSameCompany,
  blockDifferentCompany,
  blockUnattributedPending,
  blockPendingInspectionFailure,
}

typedef OfflinePendingReader =
    Future<List<Map<String, dynamic>>> Function(String companyCode);
typedef RejectedRefreshRevoker = Future<void> Function(String refreshToken);

class OfflineOwnerLoginGuardResult {
  const OfflineOwnerLoginGuardResult(this.outcome);

  final OfflineOwnerLoginOutcome outcome;

  bool get allowsLogin =>
      outcome == OfflineOwnerLoginOutcome.allowNoPendingOwner ||
      outcome == OfflineOwnerLoginOutcome.allowSameOwner ||
      outcome == OfflineOwnerLoginOutcome.allowStaleOwner;

  bool get shouldClearStaleMarker =>
      outcome == OfflineOwnerLoginOutcome.allowStaleOwner;

  bool get shouldClearMarkerAfterAcceptedSession =>
      false;
}

OfflineOwnerLoginDecision classifyOfflineOwnerLogin({
  required String? ownerCompanyCode,
  required String? ownerDriverId,
  required String returnedCompanyCode,
  required int returnedDriverId,
}) {
  final companyCode = ownerCompanyCode?.trim();
  final driverId = int.tryParse(ownerDriverId?.trim() ?? '');

  if (companyCode == null ||
      companyCode.isEmpty ||
      driverId == null ||
      driverId <= 0) {
    return OfflineOwnerLoginDecision.noOwner;
  }
  if (companyCode != returnedCompanyCode) {
    return OfflineOwnerLoginDecision.differentCompany;
  }
  if (driverId != returnedDriverId) {
    return OfflineOwnerLoginDecision.differentDriverSameCompany;
  }
  return OfflineOwnerLoginDecision.sameOwner;
}

bool hasActivePendingSyncs(Iterable<Map<String, dynamic>> pendingRows) {
  // Blocked/quarantined rows are unresolved financial/stock evidence too.
  // Their existence must continue protecting the original offline owner.
  return pendingRows.any(isUnresolvedOfflineCommand);
}

Future<void> _bestEffortRevoke(
  RejectedRefreshRevoker revokeRejectedRefresh,
  String refreshToken,
) async {
  try {
    await revokeRejectedRefresh(refreshToken);
  } catch (_) {
    // Login remains blocked even when network/session cleanup cannot complete.
  }
}

Future<OfflineOwnerLoginGuardResult> evaluateOfflineOwnerLoginSafety({
  required String? ownerCompanyCode,
  required String? ownerDriverId,
  required String returnedCompanyCode,
  required int returnedDriverId,
  required String returnedRefreshToken,
  required OfflinePendingReader readPendingSyncs,
  required RejectedRefreshRevoker revokeRejectedRefresh,
}) async {
  final normalizedOwnerCompany = ownerCompanyCode?.trim();
  final normalizedOwnerDriver = int.tryParse(ownerDriverId?.trim() ?? '');
  final hasValidOwner =
      normalizedOwnerCompany != null &&
      normalizedOwnerCompany.isNotEmpty &&
      normalizedOwnerDriver != null &&
      normalizedOwnerDriver > 0;

  if (!hasValidOwner) {
    try {
      final returnedCompanyPending = await readPendingSyncs(
        returnedCompanyCode,
      );
      if (hasActivePendingSyncs(returnedCompanyPending)) {
        await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
        return const OfflineOwnerLoginGuardResult(
          OfflineOwnerLoginOutcome.blockUnattributedPending,
        );
      }
      return const OfflineOwnerLoginGuardResult(
        OfflineOwnerLoginOutcome.allowNoPendingOwner,
      );
    } catch (_) {
      await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
      return const OfflineOwnerLoginGuardResult(
        OfflineOwnerLoginOutcome.blockPendingInspectionFailure,
      );
    }
  }

  final ownerCompany = normalizedOwnerCompany;
  final ownerDriver = normalizedOwnerDriver;

  try {
    final ownerPending = await readPendingSyncs(ownerCompany);
    if (!hasActivePendingSyncs(ownerPending)) {
      if (ownerCompany != returnedCompanyCode) {
        final returnedCompanyPending = await readPendingSyncs(
          returnedCompanyCode,
        );
        if (hasActivePendingSyncs(returnedCompanyPending)) {
          await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
          return const OfflineOwnerLoginGuardResult(
            OfflineOwnerLoginOutcome.blockUnattributedPending,
          );
        }
      }
      return const OfflineOwnerLoginGuardResult(
        OfflineOwnerLoginOutcome.allowStaleOwner,
      );
    }

    final decision = classifyOfflineOwnerLogin(
      ownerCompanyCode: ownerCompany,
      ownerDriverId: ownerDriver.toString(),
      returnedCompanyCode: returnedCompanyCode,
      returnedDriverId: returnedDriverId,
    );

    switch (decision) {
      case OfflineOwnerLoginDecision.sameOwner:
        try {
          DurableCommandOwner(companyCode: ownerCompany, driverId: ownerDriver)
            .requireRows(ownerPending);
        } on DurableCommandOwnerException {
          await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
          return const OfflineOwnerLoginGuardResult(
            OfflineOwnerLoginOutcome.blockUnattributedPending,
          );
        }
        return const OfflineOwnerLoginGuardResult(
          OfflineOwnerLoginOutcome.allowSameOwner,
        );
      case OfflineOwnerLoginDecision.differentDriverSameCompany:
        await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
        return const OfflineOwnerLoginGuardResult(
          OfflineOwnerLoginOutcome.blockDifferentDriverSameCompany,
        );
      case OfflineOwnerLoginDecision.differentCompany:
        await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
        return const OfflineOwnerLoginGuardResult(
          OfflineOwnerLoginOutcome.blockDifferentCompany,
        );
      case OfflineOwnerLoginDecision.noOwner:
        return const OfflineOwnerLoginGuardResult(
          OfflineOwnerLoginOutcome.allowNoPendingOwner,
        );
    }
  } catch (_) {
    await _bestEffortRevoke(revokeRejectedRefresh, returnedRefreshToken);
    return const OfflineOwnerLoginGuardResult(
      OfflineOwnerLoginOutcome.blockPendingInspectionFailure,
    );
  }
}
