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
    super.key,
  });

  final int driverId;

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
    _visitListBloc.add(
      RefreshVisitsEvent(completion: completion),
    );
    await completion.future;
  }

  Future<bool> _allowAction(VisitRouteAction action) async {
    final decision = await _actionGate.evaluate(action);
    if (!mounted) return false;
    if (decision != VisitRouteActionDecision.allowed) {
      showVisitRouteGateFeedback(
        context,
        action: action,
        decision: decision,
      );
      return false;
    }
    return true;
  }

  Future<void> _openAddShop() async {
    if (!await _allowAction(VisitRouteAction.addShop)) return;
    if (!mounted) return;

    final result = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (context) => const AddShopScreen(),
      ),
    );
    if (!mounted) return;
    if (result == true) {
      await _forceSync();
    }
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
          if (state is VisitListLoaded &&
              state.refreshResult != null) {
            showVisitListRefreshFeedback(
              context,
              state.refreshResult!,
            );
          }
        },
        child: BlocBuilder<VisitListBloc, VisitListState>(
          builder: (context, state) {
            final model =
                state is VisitListLoaded ? state.model : null;
            final activeRoute =
                _tabController.index == 1
                    ? VisitRouteKind.emergency
                    : VisitRouteKind.normal;
            final locale =
                Localizations.localeOf(context).toLanguageTag();

            return Scaffold(
              backgroundColor: Colors.grey.shade50,
              appBar: AppBar(
                backgroundColor: Colors.grey.shade50,
                elevation: 0,
                surfaceTintColor: Colors.transparent,
                title: Text(
                  visitListString(
                    VisitListStringKey.title,
                    localeCode: locale,
                  ),
                ),
                centerTitle: true,
                actions: [
                  IconButton(
                    onPressed: _forceSync,
                    icon: const Icon(Icons.refresh),
                    tooltip: visitListString(
                      VisitListStringKey.refreshTooltip,
                      localeCode: locale,
                    ),
                  ),
                ],
                bottom: VisitRouteTabBar(
                  controller: _tabController,
                  emergencyCount: model?.emergencyCount ?? 0,
                ),
              ),
              floatingActionButton: FloatingActionButton(
                onPressed: _openAddShop,
                tooltip: visitListString(
                  VisitListStringKey.addShopTooltip,
                  localeCode: locale,
                ),
                child: const Icon(Icons.add),
              ),
              body: _buildBody(
                state,
                activeRoute,
                locale,
              ),
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
                visitListString(
                  VisitListStringKey.retry,
                  localeCode: locale,
                ),
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
            (filter) => _visitListBloc.add(
              FilterVisitsEvent(filter),
            ),
        onRefresh: _forceSync,
        onOpenVisit: _openVisit,
        onOpenMap: _openMap,
      );
    }

    return const SizedBox.shrink();
  }
}
