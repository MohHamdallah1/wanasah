import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_state.dart';

void main() {
  test('DashboardLoaded preserves and clears refresh issue explicitly', () {
    const issue = DashboardRefreshIssue(
      kind: DashboardRefreshIssueKind.service,
      statusCode: 500,
      requestId: 'req-1',
    );

    const state = DashboardLoaded(
      visits: [],
      products: [],
      totalVisits: 0,
      completedVisits: 0,
      pendingVisits: 0,
      offlineVisits: 0,
      refreshIssue: issue,
    );

    expect(state.copyWith().refreshIssue, issue);
    expect(state.copyWith(clearRefreshIssue: true).refreshIssue, isNull);
  });

  test('refresh issue identity includes kind status and request id', () {
    const first = DashboardRefreshIssue(
      kind: DashboardRefreshIssueKind.connectivity,
      statusCode: 503,
      requestId: 'abc',
    );
    const same = DashboardRefreshIssue(
      kind: DashboardRefreshIssueKind.connectivity,
      statusCode: 503,
      requestId: 'abc',
    );
    const different = DashboardRefreshIssue(
      kind: DashboardRefreshIssueKind.service,
      statusCode: 503,
      requestId: 'abc',
    );

    expect(first, same);
    expect(first, isNot(different));
  });
}
