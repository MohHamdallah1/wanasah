part of 'package:wanasah_frontend/blocs/dashboard/dashboard_bloc.dart';

Future<void> _handleCheckPendingTransfers(
  DashboardBloc bloc,
  CheckPendingTransfers event,
  Emitter<DashboardState> emit,
) async {
  if (bloc.state is! DashboardLoaded) return;

  try {
    final response = await bloc._dashboardRepo.checkPendingTransfersRaw();
    final dynamic rawTransfers = response.data;
    final List<dynamic> transfers = rawTransfers is List ? rawTransfers : [];

    if (transfers.isNotEmpty && bloc.state is DashboardLoaded) {
      emit(
        (bloc.state as DashboardLoaded).copyWith(
          pendingTransfer: transfers.first,
        ),
      );
    }
  } catch (e) {
    developer.log('[DashboardBloc] Error checking transfers (Offline?): $e');
    try {
      final localTransfers = await bloc._db.getIncomingTransfers();
      if (localTransfers.isNotEmpty) {
        if (bloc.state is DashboardLoaded) {
          final wrappedData = {
            'items':
                localTransfers
                    .map(
                      (t) => {
                        'real_transfer_id': t['transfer_id'],
                        'product_variant_id': t['product_variant_id'],
                        'product_name': t['product_name'],
                        'delta_cartons': t['delta_cartons'],
                        'delta_packs': t['delta_packs'],
                        'status': t['status'],
                      },
                    )
                    .toList(),
          };
          emit(
            (bloc.state as DashboardLoaded).copyWith(
              pendingTransfer: wrappedData,
            ),
          );
        }
        developer.log(
          '[DashboardBloc] Loaded pending transfer from local DB.',
        );
      }
    } catch (localErr) {
      developer.log(
        '[DashboardBloc] Error reading local transfers: $localErr',
      );
    }
  }
}

Future<void> _handleRespondToTransfer(
  DashboardBloc bloc,
  RespondToTransfer event,
  Emitter<DashboardState> emit,
) async {
  if (bloc.state is! DashboardLoaded) return;

  final snapshot = bloc.state as DashboardLoaded;
  emit(snapshot.copyWith(clearPendingTransfer: true));

  try {
    final wasSentLive = await bloc._syncRepository.respondToTransfer(
      transferId: event.transferId,
      responseStr: event.responseStatus,
    );

    if (wasSentLive) {
      final int? driverId = await bloc._dashboardRepo.getDriverId();
      bloc.add(FetchDashboardData(driverId: driverId ?? 0));
    } else {
      emit(
        snapshot.copyWith(
          clearPendingTransfer: true,
          actionSuccessMessage:
              'تم حفظ ردك. سيتم إرساله تلقائياً عند عودة الإنترنت 📡',
        ),
      );
    }
  } catch (e) {
    developer.log('[DashboardBloc] Error responding to transfer: $e');
    emit(DashboardError(message: 'فشل إرسال الرد للإدارة: $e'));
    emit(snapshot);
  }
}

Future<void> _handleRespondToBatchTransfer(
  DashboardBloc bloc,
  RespondToBatchTransfer event,
  Emitter<DashboardState> emit,
) async {
  if (bloc.state is! DashboardLoaded) return;
  final snapshot = bloc.state as DashboardLoaded;
  emit(snapshot.copyWith(clearPendingTransfer: true));

  if (event.detailedTransfers.isEmpty) return;

  try {
    bool isAnyQueued = false;
    for (final t in event.detailedTransfers) {
      final tid = int.tryParse(t['transfer_id']?.toString() ?? '');
      if (tid == null) continue;

      final wasSentLive = await bloc._syncRepository.respondToTransfer(
        transferId: tid,
        responseStr: t['status'] as String,
      );

      if (!wasSentLive) isAnyQueued = true;
    }

    if (!isAnyQueued) {
      final int? driverId = await bloc._dashboardRepo.getDriverId();
      bloc.add(FetchDashboardData(driverId: driverId ?? 0));
    } else {
      emit(
        snapshot.copyWith(
          clearPendingTransfer: true,
          actionSuccessMessage:
              'تم حفظ ردك. سيتم إرساله تلقائياً عند عودة الإنترنت 📡',
        ),
      );
    }
  } catch (e) {
    developer.log('[DashboardBloc] Error responding to batch: $e');
    emit(
      DashboardError(
        message: e.toString().replaceAll('Exception: ', ''),
      ),
    );
    emit(snapshot);
  }
}
