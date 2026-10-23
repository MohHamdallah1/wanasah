abstract interface class VisitReplayAdapter {
  Future<void> dispatch(Map<String, dynamic> payload);

  Future<void> finalizeLocalState({
    required int commandRecordId,
    required Map<String, dynamic> payload,
  });
}
