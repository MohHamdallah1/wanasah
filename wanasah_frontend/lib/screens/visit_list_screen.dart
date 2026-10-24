import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../blocs/visit_list/visit_list_bloc.dart';
import '../blocs/visit_list/visit_list_event.dart';
import '../blocs/visit_list/visit_list_state.dart';
import '../features/visits/list/application/visit_list_read_model.dart';
import '../features/visits/list/application/visit_route_action_gate.dart';
import '../features/visits/list/presentation/visit_list_feedback.dart';
import '../features/visits/list/presentation/visit_list_strings.dart';
import '../features/visits/list/presentation/visit_map_launcher.dart';
import '../features/visits/list/presentation/visit_route_tabs.dart';
import 'add_shop_screen.dart';
import 'visit_screen.dart';

class VisitListScreen extends StatefulWidget {
  const VisitListScreen({
    required this.driverId,
    this.embedded = false,
    this.onReturnFromAction,
    super.key,
  });

  final int driverId;
  final bool embedded;
  final VoidCallback? onReturnFromAction;

  @override
  State<VisitListScreen> createState() => _VisitListScreenState();
}

class _VisitListScreenState extends State<VisitListScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  late final VisitListBloc _visitListBloc;
  late final VisitRouteActionGate _actionGate;
  final VisitMapLauncher _mapLauncher = const VisitMapLauncher();

  @override
  void initState() {
    super.initState();
    _visitListBloc = VisitListBloc()..add(const LoadVisitsEvent());
    _actionGate = const VisitRouteActionGate();
    _tabController = TabController(length: 2, vsync: this)
      ..addListener(_handleTabChanged);
  }

  void _handleTabChanged() {
    if (mounted && !_tabController.indexIsChanging) {
      setState(() {});
    }
  }

  @override
  void dispose() {
    _tabController
      ..removeListener(_handleTabChanged)
      ..dispose();
    _visitListBloc.close();
    super.dispose();
  }

  Future<void> _forceSync() async {
    final completion = Completer<void>();
    _visitListBloc.add(RefreshVisitsEvent(completion: completion));
    await completion.future;
  }

  Future<bool> _allowAction(VisitRouteAction action) async {
    final decision = await _actionGate.evaluate(action);
    if (!mounted) return false;
    if (decision != VisitRouteActionDecision.allowed) {
      showVisitRouteGateFeedback(context, action: action, decision: decision);
      return false;
    }
    return true;
  }

  Future<void> _openAddShop() async {
    if (!await _allowAction(VisitRouteAction.addShop)) return;
    if (!mounted) return;

    final result = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (context) => const AddShopScreen()),
    );
    if (!mounted) return;
    if (result == true) {
      await _forceSync();
    }
    if (mounted) widget.onReturnFromAction?.call();
  }

  Future<void> _openVisit(VisitListRow row) async {
    if (!await _allowAction(VisitRouteAction.openVisit)) return;
    if (!mounted) return;

    await Navigator.push<void>(
      context,
      MaterialPageRoute(
        builder:
            (context) => VisitScreen(
              visitId: row.id,
              shopName: row.shopName,
              shopBalance: row.shopBalance,
              visitStatus: row.backendStatus,
            ),
      ),
    );

    if (mounted) {
      _visitListBloc.add(const LoadVisitsEvent());
      widget.onReturnFromAction?.call();
    }
  }

  Future<void> _openMap(VisitListRow row) async {
    final outcome = await _mapLauncher.open(row);
    if (!mounted) return;
    showVisitMapFeedback(context, outcome);
  }

  @override
  Widget build(BuildContext context) {
    return BlocProvider.value(
      value: _visitListBloc,
      child: BlocListener<VisitListBloc, VisitListState>(
        listener: (context, state) {
          if (state is VisitListLoaded && state.refreshResult != null) {
            showVisitListRefreshFeedback(context, state.refreshResult!);
          }
        },
        child: BlocBuilder<VisitListBloc, VisitListState>(
          builder: (context, state) {
            final model = state is VisitListLoaded ? state.model : null;
            final activeRoute =
                _tabController.index == 1
                    ? VisitRouteKind.emergency
                    : VisitRouteKind.normal;
            final locale = Localizations.localeOf(context).toLanguageTag();

            return Scaffold(
              backgroundColor:
                  widget.embedded
                      ? Theme.of(context).colorScheme.surface
                      : Colors.grey.shade50,
              appBar: AppBar(
                automaticallyImplyLeading: !widget.embedded,
                primary: !widget.embedded,
                toolbarHeight: widget.embedded ? 64 : 60,
                titleSpacing: widget.embedded ? 12 : null,
                backgroundColor: Theme.of(context).colorScheme.surface,
                elevation: 0,
                scrolledUnderElevation: 0,
                surfaceTintColor: Colors.transparent,
                title:
                    widget.embedded
                        ? VisitRouteTabBar(
                          controller: _tabController,
                          emergencyCount: model?.emergencyCount ?? 0,
                        )
                        : Text(
                          visitListString(
                            VisitListStringKey.title,
                            localeCode: locale,
                          ),
                          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w850,
                          ),
                        ),
                centerTitle: !widget.embedded,
                actions: [
                  Padding(
                    padding: const EdgeInsetsDirectional.only(end: 6),
                    child: IconButton.filledTonal(
                      onPressed: _forceSync,
                      icon: const Icon(Icons.refresh_rounded),
                      tooltip: visitListString(
                        VisitListStringKey.refreshTooltip,
                        localeCode: locale,
                      ),
                    ),
                  ),
                ],
                bottom:
                    widget.embedded
                        ? null
                        : VisitRouteTabBar(
                          controller: _tabController,
                          emergencyCount: model?.emergencyCount ?? 0,
                        ),
              ),
              floatingActionButtonLocation:
                  FloatingActionButtonLocation.startFloat,
              floatingActionButton: FloatingActionButton.extended(
                key: const ValueKey('visit-add-shop'),
                onPressed: _openAddShop,
                tooltip: visitListString(
                  VisitListStringKey.addShopTooltip,
                  localeCode: locale,
                ),
                icon: const Icon(Icons.add_business_outlined),
                label: Text(
                  visitListString(
                    VisitListStringKey.addShopTooltip,
                    localeCode: locale,
                  ),
                ),
              ),
              body: _buildBody(state, activeRoute, locale),
            );
          },
        ),
      ),
    );
  }

  Widget _buildBody(
    VisitListState state,
    VisitRouteKind activeRoute,
    String locale,
  ) {
    if (state is VisitListLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (state is VisitListError) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              visitListString(
                VisitListStringKey.loadFailure,
                localeCode: locale,
              ),
              style: const TextStyle(color: Colors.red),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 10),
            ElevatedButton(
              onPressed: _forceSync,
              child: Text(
                visitListString(VisitListStringKey.retry, localeCode: locale),
              ),
            ),
          ],
        ),
      );
    }

    if (state is VisitListLoaded) {
      return VisitRouteTabs(
        controller: _tabController,
        model: state.model,
        activeRoute: activeRoute,
        onFilterChanged:
            (filter) => _visitListBloc.add(FilterVisitsEvent(filter)),
        onRefresh: _forceSync,
        onOpenVisit: _openVisit,
        onOpenMap: _openMap,
      );
    }

    return const SizedBox.shrink();
  }
}
