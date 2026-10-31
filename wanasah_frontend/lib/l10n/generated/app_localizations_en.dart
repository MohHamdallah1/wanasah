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

  @override
  String get homeTodayRoute => 'Today\'s route';

  @override
  String get homeCompletedLabel => 'Completed';

  @override
  String get homeRemainingLabel => 'Remaining';

  @override
  String get homeSalesLabel => 'Sales';

  @override
  String homeAwaitingSync(String count) {
    return '$count visits awaiting sync';
  }

  @override
  String get homeCashReceived => 'Total cash received';

  @override
  String get homeCashSales => 'Cash sales';

  @override
  String get homeDebtCollections => 'Debt collections';

  @override
  String homeDebtOperations(String count) {
    return '$count operations';
  }

  @override
  String get workSessionReadyStatus => 'Ready to start';

  @override
  String get workSessionActiveStatus => 'Work in progress';

  @override
  String get workSessionBreakStatus => 'On break';

  @override
  String get workSessionReadyTitle => 'Start your day';

  @override
  String get workSessionActiveTitle => 'Route in progress';

  @override
  String get workSessionBreakTitle => 'You are on a break';

  @override
  String get workSessionReadyHint => 'Start the work session when you are ready to head out.';

  @override
  String get workSessionActiveHint => 'The current work session is active and today\'s work continues.';

  @override
  String get workSessionBreakHint => 'The session is preserved. End the break when you are ready to continue.';

  @override
  String get workSessionStartUnknown => 'Session start time is unavailable.';

  @override
  String workSessionStartedAt(String time) {
    return 'Started $time';
  }

  @override
  String workSessionElapsed(String duration) {
    return 'Elapsed $duration';
  }

  @override
  String get workSessionStartAction => 'Start work';

  @override
  String get workSessionEndAction => 'End work';

  @override
  String get workSessionStartBreakAction => 'Start break';

  @override
  String get workSessionEndBreakAction => 'End break';

  @override
  String get workSessionConfirmStartTitle => 'Start work?';

  @override
  String get workSessionConfirmStartBody => 'Do you want to start a new work session?';

  @override
  String get workSessionConfirmEndTitle => 'End work?';

  @override
  String get workSessionConfirmEndBody => 'Do you want to end the current work session?';

  @override
  String get workSessionStartSuccess => 'Work session started.';

  @override
  String get workSessionEndSuccess => 'Work session ended.';

  @override
  String get workSessionBreakStartSuccess => 'Break started and recorded by the server.';

  @override
  String get workSessionBreakEndSuccess => 'Break ended and recorded by the server.';

  @override
  String get workSessionStartReconciled => 'The active work session was confirmed with the server.';

  @override
  String get workSessionEndReconciled => 'The ended work session was confirmed with the server.';

  @override
  String get workSessionBreakStartReconciled => 'The break start was confirmed with the server.';

  @override
  String get workSessionBreakEndReconciled => 'The break end was confirmed with the server.';

  @override
  String get workSessionUnresolved => 'The operation result could not be confirmed. Refresh before retrying.';

  @override
  String get workSessionAuthRejected => 'The session expired or this action is not authorized.';

  @override
  String get workSessionBusinessRejected => 'The server rejected the action because of the current work state.';

  @override
  String get workSessionRateLimited => 'Too many requests. Try again shortly.';

  @override
  String get workSessionNetworkUnresolved => 'The result could not be confirmed because of connectivity. Server state remains authoritative.';

  @override
  String get workSessionTimeoutUnresolved => 'The request timed out before the result was confirmed. Server state remains authoritative.';

  @override
  String get workSessionServerUnresolved => 'The result could not be confirmed because of a server error.';

  @override
  String get workSessionRequestIdLabel => 'Request ID';

  @override
  String get workSessionStatusCodeLabel => 'Status code';

  @override
  String get workSessionServerDetailLabel => 'Server detail';

  @override
  String get workSessionIssueAuthentication => 'Sign in again before performing this work-session action.';

  @override
  String get workSessionIssueInvalidStartEvidence => 'The start-session request evidence was invalid. Refresh the data and try again.';

  @override
  String get workSessionIssueVehicleCustody => 'The vehicle custody is not operationally ready. Contact dispatch or custody operations.';

  @override
  String get workSessionIssueStartPrerequisite => 'The server refused to start work because a route, vehicle, or custody prerequisite is not ready.';

  @override
  String get workSessionIssueEndPrerequisite => 'The server refused to end work because an operational prerequisite remains unresolved.';

  @override
  String get workSessionIssueBreakState => 'The server break state does not allow this action. Refresh the session state and try again.';

  @override
  String get workSessionIssueRateLimited => 'The work-session action was rate limited. Try again shortly.';

  @override
  String get workSessionIssueConnectivity => 'The server could not be reached. Check the connection and refresh session state before retrying.';

  @override
  String get workSessionIssueTimeout => 'The request timed out before the result was confirmed. Refresh session state before retrying.';

  @override
  String get workSessionIssueUnresolved => 'The work-session result is unresolved. Server state remains authoritative; refresh before retrying.';

  @override
  String get visitListTitle => 'Route';

  @override
  String get visitRefreshTooltip => 'Refresh route';

  @override
  String get visitNormalRouteTab => 'Today\'s route';

  @override
  String get visitEmergencyRouteTab => 'Urgent requests';

  @override
  String visitFilterAll(String count) {
    return 'All $count';
  }

  @override
  String visitFilterCompleted(String count) {
    return 'Completed $count';
  }

  @override
  String visitFilterPending(String count) {
    return 'Remaining $count';
  }

  @override
  String get visitStatusCompleted => 'Completed';

  @override
  String get visitStatusPending => 'Pending';

  @override
  String get visitStatusAttempted => 'Attempted';

  @override
  String get visitStatusPostponed => 'Postponed';

  @override
  String get visitStatusNoSale => 'No sale';

  @override
  String visitStatusUnknown(String status) {
    return 'Unknown status ($status)';
  }

  @override
  String visitBalanceLabel(String amount) {
    return 'Balance: $amount JOD';
  }

  @override
  String get visitMapTooltip => 'Open shop location';

  @override
  String get visitEmptyNormalAll => 'No scheduled visits right now.';

  @override
  String get visitEmptyEmergencyAll => 'No urgent requests right now.';

  @override
  String get visitEmptyNormalPending => 'No remaining visits.';

  @override
  String get visitEmptyEmergencyPending => 'No remaining urgent requests.';

  @override
  String get visitEmptyNormalCompleted => 'No completed visits yet.';

  @override
  String get visitEmptyEmergencyCompleted => 'No completed urgent requests yet.';

  @override
  String get visitAddShopAction => 'Add shop';

  @override
  String get visitGateOnBreak => 'You are on break. End the break before continuing.';

  @override
  String get visitGateUnauthorizedAdd => 'You are not authorized to add shops.';

  @override
  String get visitGateUnauthorizedOpen => 'You are not authorized to open this visit.';

  @override
  String get visitGateUnavailable => 'Work-session and authorization state could not be confirmed. Refresh and try again.';

  @override
  String get visitRefreshSuccess => 'Visit list refreshed.';

  @override
  String get visitRefreshAlreadySyncing => 'A sync is already running elsewhere.';

  @override
  String get visitRefreshTransportAmbiguous => 'The refresh result could not be confirmed because of connectivity. Local data is shown.';

  @override
  String get visitRefreshBlocked => 'Unresolved offline work prevents replacing local data.';

  @override
  String get visitRefreshDeterministicFailure => 'The visit list could not be refreshed.';

  @override
  String get visitLoadFailure => 'The local visit list could not be loaded.';

  @override
  String get visitMapNoLocation => 'No location is recorded for this shop.';

  @override
  String get visitMapNoApplication => 'No maps app or valid external location link is available.';

  @override
  String get visitMapInvalidLink => 'The location link is invalid.';

  @override
  String get visitMapOpenFailed => 'The shop location could not be opened.';

  @override
  String get visitRequestIdLabel => 'Request ID';

  @override
  String visitRouteOverview(String total, String completed, String pending) {
    return '$total visits • $completed completed • $pending remaining';
  }

  @override
  String get visitNextLabel => 'Next';

  @override
  String get visitUrgentLabel => 'Urgent';

  @override
  String get visitOpenVisitHint => 'Open visit';

  @override
  String get stockVehicleTitle => 'Vehicle inventory:';

  @override
  String get stockEmptyVerified => 'No sellable stock is currently in the vehicle.';

  @override
  String get stockUnavailable => 'Vehicle stock could not be verified; balance is unknown.';

  @override
  String get stockDenied => 'You do not have access to current custody.';

  @override
  String get stockStale => 'Saved offline stock; not a verified current balance.';

  @override
  String get stockReceived => 'Received';

  @override
  String get stockSold => 'Sold';

  @override
  String get stockRemaining => 'Remaining';

  @override
  String get stockCarton => 'cartons';

  @override
  String get stockPack => 'packs';

  @override
  String get stockPiece => 'pieces';

  @override
  String get stockPendingReturns => 'Local returns pending resolution:';

  @override
  String get stockPendingReturnsHint => 'These are pending local records, not final server custody.';

  @override
  String get stockNonSellableTitle => 'Non-sellable custody:';

  @override
  String get stockStatusDamaged => 'Damaged';

  @override
  String get stockStatusQuarantined => 'Quarantined';

  @override
  String get stockStatusBlocked => 'Blocked';

  @override
  String get stockStatusRecalled => 'Recalled';

  @override
  String get stockStatusDisposalPending => 'Awaiting disposal';

  @override
  String get stockPending => 'Pending sync';

  @override
  String get stockInFlight => 'Sending';

  @override
  String get stockNeedsAction => 'Needs attention';

  @override
  String get stockReasonExpired => 'Expired';

  @override
  String get stockReasonFactory => 'Factory defect';

  @override
  String get stockAvailableLocal => 'Locally available (not currently verified)';

  @override
  String get stockSearchHint => 'Search products...';

  @override
  String get stockConfirmQuantities => 'Confirm quantities and return to invoice';

  @override
  String get stockSaleCartons => 'Sale cartons';

  @override
  String get stockSalePacks => 'Sale pieces';

  @override
  String get stockSampleCartons => 'Sample cartons (🎁)';

  @override
  String get stockSamplePacks => 'Sample pieces (🎁)';

  @override
  String get stockSampleReasonHint => 'Select sample reason (required)';

  @override
  String get stockSampleReasonDetailsHint => 'Describe the reason...';

  @override
  String get stockSampleReasonPromo => 'New product promotion';

  @override
  String get stockSampleReasonFree => 'Free customer sample';

  @override
  String get stockSampleReasonCompensation => 'Shop goodwill compensation';

  @override
  String get stockSampleReasonOther => 'Other';
}
