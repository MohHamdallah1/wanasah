// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'Wanasah';

  @override
  String get dashboardConnectivityCached => 'The service is temporarily unreachable. Saved data remains available.';

  @override
  String get dashboardServiceCached => 'The service could not refresh your data. Saved data remains available.';

  @override
  String get dashboardGenericError => 'Unable to load this data. Try again or contact support.';

  @override
  String get retry => 'Try again';

  @override
  String get home => 'Home';

  @override
  String get route => 'Route';

  @override
  String get custody => 'Custody';

  @override
  String get brand => 'Wanasah';

  @override
  String get account => 'Account';

  @override
  String get refresh => 'Refresh data';

  @override
  String get logout => 'Sign out';

  @override
  String get logoutTitle => 'Confirm sign out';

  @override
  String get logoutPrompt => 'Do you want to sign out?';

  @override
  String get cancel => 'Cancel';

  @override
  String get confirm => 'Confirm';

  @override
  String greeting(String name) {
    return 'Welcome, $name!';
  }

  @override
  String region(String region) {
    return 'Assigned region: $region';
  }

  @override
  String today(String date) {
    return 'Today: $date';
  }

  @override
  String get routeSummary => 'Route summary';

  @override
  String completedVisits(String count) {
    return 'Completed visits: $count';
  }

  @override
  String salesVisits(String count) {
    return 'Visits with sales: $count';
  }

  @override
  String pendingVisits(String count) {
    return 'Pending visits: $count';
  }

  @override
  String offlineVisits(String count) {
    return 'Awaiting sync: $count';
  }

  @override
  String get financialSummary => 'Financial summary';

  @override
  String salesCash(String amount) {
    return 'Sales cash: $amount';
  }

  @override
  String debtCash(String count, String amount) {
    return 'Debt collections: ($count) $amount';
  }

  @override
  String totalCash(String amount) {
    return 'Total cash received: $amount';
  }

  @override
  String get pendingTransfers => 'Review pending transfers';

  @override
  String get recoveryChecking => 'Checking';

  @override
  String get recoveryNoPending => 'No pending work';

  @override
  String recoveryPendingCompact(String count) {
    return 'Pending: $count';
  }

  @override
  String recoveryBlockedCompact(String count) {
    return 'Attention: $count';
  }

  @override
  String get recoveryUnavailableCompact => 'Status unconfirmed';

  @override
  String get recoveryUnreachableCompact => 'Service unreachable';

  @override
  String get recoveryServiceCompact => 'Service refresh failed';

  @override
  String get recoveryCachedCompact => 'Saved data';

  @override
  String get recoverySyncingCompact => 'Syncing';

  @override
  String get recoveryRefreshAction => 'Sync and refresh';

  @override
  String get recoveryInspectAction => 'Recheck status';

  @override
  String get recoveryDetailsAction => 'View saved evidence';

  @override
  String recoveryPendingBanner(String count) {
    return 'Waiting to sync: $count';
  }

  @override
  String recoveryBlockedBanner(String count) {
    return 'Recovery required: $count';
  }

  @override
  String recoveryCombinedBanner(String pending, String blocked) {
    return 'Waiting to sync: $pending • Recovery required: $blocked';
  }

  @override
  String get recoveryDetailsHint => 'Tap for details.';

  @override
  String get recoveryPanelTitle => 'Sync and recovery status';

  @override
  String get recoveryPanelDescription => 'Pending and blocked records are durable evidence. They are not deleted to hide errors.';

  @override
  String get recoveryPendingSection => 'Waiting to sync';

  @override
  String get recoveryBlockedSection => 'Recovery required';

  @override
  String get recoveryPendingState => 'Pending';

  @override
  String get recoveryBlockedState => 'Blocked';

  @override
  String get recoveryOperationLabel => 'Operation';

  @override
  String get recoveryCommandIdLabel => 'Command ID';

  @override
  String get recoveryLocalRecordLabel => 'Local record';

  @override
  String get recoveryAttemptsLabel => 'Attempts';

  @override
  String get recoveryErrorCodeLabel => 'Error code';

  @override
  String get recoveryRequestIdLabel => 'Request ID';

  @override
  String get recoveryCreatedAtLabel => 'Created';

  @override
  String get recoveryVisitLabel => 'Visit';

  @override
  String get recoveryTransferLabel => 'Transfer';

  @override
  String get recoveryReferenceLabel => 'Reference';

  @override
  String get recoveryReasonLabel => 'Detail';

  @override
  String get recoveryMissingValue => 'Unavailable';

  @override
  String get recoveryNoRecoveryItems => 'No pending or blocked operations.';

  @override
  String get recoveryReadUnavailable => 'Local sync state could not be read. It was not assumed to be empty.';

  @override
  String get recoverySyncInProgress => 'Syncing durable offline work…';

  @override
  String get recoverySyncSuccess => 'Sync completed.';

  @override
  String get recoverySyncIncomplete => 'Sync is incomplete; pending operations remain.';

  @override
  String get recoverySyncRecoveryRequired => 'Blocked operations require recovery before sync can be considered complete.';

  @override
  String get recoverySyncConnectivityUnresolved => 'Connectivity was lost during sync. Local evidence remains preserved.';

  @override
  String get recoverySyncTimedOut => 'Sync timed out before the result was confirmed. Local evidence remains preserved.';

  @override
  String get recoverySyncUnresolved => 'The sync result could not be confirmed. Local evidence remains preserved.';

  @override
  String get recoverySubmitSale => 'Visit / invoice';

  @override
  String get recoveryTransferResponse => 'Transfer response';

  @override
  String get recoveryLegacyBreak => 'Legacy break';

  @override
  String get recoveryCorrupt => 'Invalid record';

  @override
  String get recoveryUnknownOperation => 'Unknown operation';

  @override
  String get recoveryReadOnlyNotice => 'Blocked records are read-only here and there is no bulk-delete action.';
}
