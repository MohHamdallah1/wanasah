import 'dart:developer' as developer;

import 'package:dio/dio.dart';

import '../data/work_session_remote_data_source.dart';
import 'work_session_failure.dart';
import 'work_session_location_source.dart';
import 'work_session_outcome.dart';

class WorkSessionCoordinator {
  WorkSessionCoordinator({
    required WorkSessionRemoteDataSource remote,
    required WorkSessionLocationSource locationSource,
  }) : _remote = remote,
       _locationSource = locationSource;

  final WorkSessionRemoteDataSource _remote;
  final WorkSessionLocationSource _locationSource;

  Future<WorkSessionRecoveryResult> recoverActiveSession() async {
    try {
      return WorkSessionRecoveryResult.success(
        await _remote.readActiveSession(),
      );
    } on DioException catch (error) {
      return WorkSessionRecoveryResult.failure(
        WorkSessionFailure.fromDioException(error),
      );
    } catch (_) {
      return const WorkSessionRecoveryResult.failure(
        WorkSessionFailure.unknown(),
      );
    }
  }

  Future<WorkSessionOperationResult> startSession() async {
    final coordinates = await _optionalCoordinates();

    try {
      await _remote.startSession(
        latitude: coordinates?.latitude,
        longitude: coordinates?.longitude,
      );
      return const WorkSessionOperationResult(
        operation: WorkSessionOperation.start,
        disposition: WorkSessionDisposition.success,
      );
    } on DioException catch (error) {
      final failure = WorkSessionFailure.fromDioException(error);
      if (!failure.isAmbiguousMutation) {
        return WorkSessionOperationResult(
          operation: WorkSessionOperation.start,
          disposition: WorkSessionDisposition.rejected,
          failure: failure,
        );
      }

      return _reconcileStart(failure);
    } catch (_) {
      return const WorkSessionOperationResult(
        operation: WorkSessionOperation.start,
        disposition: WorkSessionDisposition.unresolved,
        failure: WorkSessionFailure.unknown(),
      );
    }
  }

  Future<WorkSessionOperationResult> endSession() async {
    try {
      await _remote.endSession();
      return const WorkSessionOperationResult(
        operation: WorkSessionOperation.end,
        disposition: WorkSessionDisposition.success,
      );
    } on DioException catch (error) {
      final failure = WorkSessionFailure.fromDioException(error);
      if (!failure.isAmbiguousMutation) {
        return WorkSessionOperationResult(
          operation: WorkSessionOperation.end,
          disposition: WorkSessionDisposition.rejected,
          failure: failure,
        );
      }

      return _reconcileEnd(failure);
    } catch (_) {
      return const WorkSessionOperationResult(
        operation: WorkSessionOperation.end,
        disposition: WorkSessionDisposition.unresolved,
        failure: WorkSessionFailure.unknown(),
      );
    }
  }

  Future<WorkSessionOperationResult> toggleBreak({
    required bool start,
  }) async {
    final operation =
        start
            ? WorkSessionOperation.startBreak
            : WorkSessionOperation.endBreak;

    try {
      await _remote.toggleBreak(start: start);
      return WorkSessionOperationResult(
        operation: operation,
        disposition: WorkSessionDisposition.success,
      );
    } on DioException catch (error) {
      final failure = WorkSessionFailure.fromDioException(error);
      if (!failure.isAmbiguousMutation) {
        return WorkSessionOperationResult(
          operation: operation,
          disposition: WorkSessionDisposition.rejected,
          failure: failure,
        );
      }

      return _reconcileBreak(
        operation: operation,
        desiredOnBreak: start,
        failure: failure,
      );
    } catch (_) {
      return WorkSessionOperationResult(
        operation: operation,
        disposition: WorkSessionDisposition.unresolved,
        failure: const WorkSessionFailure.unknown(),
      );
    }
  }

  Future<WorkSessionOperationResult> _reconcileStart(
    WorkSessionFailure failure,
  ) async {
    final recovery = await recoverActiveSession();
    if (recovery.succeeded) {
      final session = recovery.session!;
      return WorkSessionOperationResult(
        operation: WorkSessionOperation.start,
        disposition:
            session.isActive
                ? WorkSessionDisposition.reconciledSuccess
                : WorkSessionDisposition.unresolved,
        failure: failure,
        reconciledSession: session,
      );
    }

    return WorkSessionOperationResult(
      operation: WorkSessionOperation.start,
      disposition: WorkSessionDisposition.unresolved,
      failure: failure,
      reconciliationFailure: recovery.failure,
    );
  }

  Future<WorkSessionOperationResult> _reconcileEnd(
    WorkSessionFailure failure,
  ) async {
    final recovery = await recoverActiveSession();
    if (recovery.succeeded) {
      final session = recovery.session!;
      return WorkSessionOperationResult(
        operation: WorkSessionOperation.end,
        disposition:
            session.isActive
                ? WorkSessionDisposition.unresolved
                : WorkSessionDisposition.reconciledSuccess,
        failure: failure,
        reconciledSession: session,
      );
    }

    return WorkSessionOperationResult(
      operation: WorkSessionOperation.end,
      disposition: WorkSessionDisposition.unresolved,
      failure: failure,
      reconciliationFailure: recovery.failure,
    );
  }

  Future<WorkSessionOperationResult> _reconcileBreak({
    required WorkSessionOperation operation,
    required bool desiredOnBreak,
    required WorkSessionFailure failure,
  }) async {
    try {
      final session = await _remote.readRuntimeSession();
      final desiredStateConfirmed =
          session.isActive && session.isOnBreak == desiredOnBreak;

      return WorkSessionOperationResult(
        operation: operation,
        disposition:
            desiredStateConfirmed
                ? WorkSessionDisposition.reconciledSuccess
                : WorkSessionDisposition.unresolved,
        failure: failure,
        reconciledSession: session,
      );
    } on DioException catch (error) {
      return WorkSessionOperationResult(
        operation: operation,
        disposition: WorkSessionDisposition.unresolved,
        failure: failure,
        reconciliationFailure: WorkSessionFailure.fromDioException(error),
      );
    } catch (_) {
      return WorkSessionOperationResult(
        operation: operation,
        disposition: WorkSessionDisposition.unresolved,
        failure: failure,
        reconciliationFailure: const WorkSessionFailure.unknown(),
      );
    }
  }

  Future<WorkSessionCoordinates?> _optionalCoordinates() async {
    try {
      final coordinates = await _locationSource.currentCoordinates();
      if (coordinates != null && !coordinates.isContractValid) {
        developer.log(
          '[WorkSession] Ignoring invalid optional location evidence; '
          'Backend remains session authority.',
        );
        return null;
      }
      return coordinates;
    } catch (error) {
      // Backend SessionStartRequest accepts nullable coordinates. Device
      // location evidence is therefore best-effort; it never becomes a
      // client-side authorization/business gate.
      developer.log(
        '[WorkSession] Location unavailable; Backend remains authoritative: '
        '$error',
      );
      return null;
    }
  }
}
