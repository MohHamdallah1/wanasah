import '../data/visit_route_action_state_source.dart';

enum VisitRouteAction {
  addShop,
  openVisit,
}

enum VisitRouteActionDecision {
  allowed,
  onBreak,
  unauthorized,
  unavailable,
}

class VisitRouteActionGate {
  VisitRouteActionGate({
    required VisitRouteActionStateSource source,
  }) : _source = source;

  final VisitRouteActionStateSource _source;

  Future<VisitRouteActionDecision> evaluate(
    VisitRouteAction action,
  ) async {
    final VisitRouteCompatibilityState state;
    try {
      state = await _source.readCompatibilityState();
    } catch (_) {
      return VisitRouteActionDecision.unavailable;
    }

    final onBreak = _strictBool(state.isOnBreak);
    final authorized = _strictBool(state.isAuthorized);

    if (onBreak == null || authorized == null) {
      return VisitRouteActionDecision.unavailable;
    }
    if (onBreak) {
      return VisitRouteActionDecision.onBreak;
    }
    if (!authorized) {
      return VisitRouteActionDecision.unauthorized;
    }
    return VisitRouteActionDecision.allowed;
  }

  bool? _strictBool(String? raw) {
    final value = raw?.trim().toLowerCase();
    if (value == 'true') return true;
    if (value == 'false') return false;
    return null;
  }
}
