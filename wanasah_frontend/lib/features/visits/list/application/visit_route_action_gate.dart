enum VisitRouteAction {
  addShop,
  openVisit,
}

// Retained for existing feedback/composition compatibility. Cached state never
// produces a denial: opening a form is not Backend acceptance of its mutation.
enum VisitRouteActionDecision {
  allowed,
  onBreak,
  unauthorized,
  unavailable,
}

/// Navigation policy only. No cached flags, permissions or live preflight.
/// Visit staging and Shop creation keep their distinct existing contracts;
/// the respective Backend mutation decides current business eligibility.
class VisitRouteActionGate {
  const VisitRouteActionGate();

  Future<VisitRouteActionDecision> evaluate(VisitRouteAction action) async =>
      VisitRouteActionDecision.allowed;
}
