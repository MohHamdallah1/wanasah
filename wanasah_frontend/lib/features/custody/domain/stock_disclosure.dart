/// A quantity is physical/current only after an authorized verified read.
/// Offline/local evidence is useful, but never silently promoted to live.
enum StockDisclosure { verified, stale, unavailable, denied }
