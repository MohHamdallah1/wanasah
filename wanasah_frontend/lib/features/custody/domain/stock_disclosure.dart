/// A quantity is physical/current only after an authorized verified read.
/// Offline/local evidence is useful, but never silently promoted to live.
enum StockDisclosure { verified, stale, unavailable, denied }

/// A confirmed refusal erases the live disclosure. A transport/service failure
/// may keep an earlier authorized view only when clearly marked stale.
/// Never turn a previous denial or unknown state into numeric zero.
StockDisclosure stockDisclosureAfterFailure(
  StockDisclosure previous, {
  required bool denied,
}) {
  if (denied || previous == StockDisclosure.denied) {
    return StockDisclosure.denied;
  }
  if (previous == StockDisclosure.verified ||
      previous == StockDisclosure.stale) {
    return StockDisclosure.stale;
  }
  return StockDisclosure.unavailable;
}
