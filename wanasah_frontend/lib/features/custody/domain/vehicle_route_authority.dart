import 'package:equatable/equatable.dart';

/// Authorized current-route evidence from GET /driver/dashboard only.
///
/// This is *not* vehicle custody ownership or a locally cached work session.
/// A missing contract or a legacy read is unknown, never "no route".
enum VehicleRouteKind { unverified, noActiveRoute, active }

class VehicleRouteAuthority extends Equatable {
  const VehicleRouteAuthority._(this.kind, this.routeId, this.vehicleId);

  const VehicleRouteAuthority.unverified()
    : this._(VehicleRouteKind.unverified, null, null);
  const VehicleRouteAuthority.noActiveRoute()
    : this._(VehicleRouteKind.noActiveRoute, null, null);
  const VehicleRouteAuthority.active({
    required int routeId,
    required int vehicleId,
  }) : this._(VehicleRouteKind.active, routeId, vehicleId);

  final VehicleRouteKind kind;
  final int? routeId;
  final int? vehicleId;

  factory VehicleRouteAuthority.fromDashboard(Map<String, dynamic> data) {
    // Treat responses from an older server as unknown, NOT no-route.
    if (!data.containsKey('active_route_vehicle')) {
      return const VehicleRouteAuthority.unverified();
    }
    final raw = data['active_route_vehicle'];
    if (raw == null) return const VehicleRouteAuthority.noActiveRoute();
    if (raw is! Map) {
      throw const FormatException('Invalid current FIELD route evidence');
    }
    final route = raw['route_id'];
    final vehicle = raw['vehicle_id'];
    if (route is! int || route <= 0 || vehicle is! int || vehicle <= 0) {
      throw const FormatException('Invalid current FIELD route vehicle');
    }
    final context = data['execution_context'];
    // Canonical execution proof, if supplied, must match the same route/car.
    if (context != null &&
        (context is! Map ||
            context['route_id'] != route ||
            context['vehicle_id'] != vehicle)) {
      throw const FormatException('FIELD route/vehicle authority conflict');
    }
    return VehicleRouteAuthority.active(routeId: route, vehicleId: vehicle);
  }

  @override
  List<Object?> get props => [kind, routeId, vehicleId];
}
