import 'package:flutter/material.dart';

import '../localization/app_copy.dart';
import '../theme/field_theme.dart';

enum FieldDestination { home, route, custody }

enum _AccountAction { refresh, logout }

/// Navigation/presentation only. Features retain their state and authorities.
/// Primary tabs stay mounted; deep mutation routes use the existing Navigator.
class FieldAppShell extends StatefulWidget {
  const FieldAppShell({
    required this.homeBuilder,
    required this.routeBuilder,
    required this.custody,
    required this.statusUtility,
    required this.accountName,
    required this.onRefresh,
    required this.onLogout,
    required this.onDestinationChanged,
    super.key,
  });

  final WidgetBuilder homeBuilder;
  final WidgetBuilder routeBuilder;
  final Widget custody;
  final Widget statusUtility;
  final String accountName;
  final VoidCallback onRefresh;
  final VoidCallback onLogout;
  final ValueChanged<FieldDestination> onDestinationChanged;

  @override
  State<FieldAppShell> createState() => _FieldAppShellState();
}

class _FieldAppShellState extends State<FieldAppShell> {
  FieldDestination _selected = FieldDestination.home;
  bool _routeOpened = false;

  void _select(FieldDestination destination) {
    if (destination == _selected) return;
    setState(() {
      _selected = destination;
      _routeOpened |= destination == FieldDestination.route;
    });
    widget.onDestinationChanged(destination);
  }

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: FieldTheme.data(),
      child: Builder(
        builder: (context) {
          final colors = Theme.of(context).colorScheme;
          final compactBrand =
              MediaQuery.sizeOf(context).width < 360 ||
              MediaQuery.textScalerOf(context).scale(20) > 28;
          return PopScope(
            canPop: _selected == FieldDestination.home,
            onPopInvokedWithResult: (didPop, _) {
              if (!didPop) _select(FieldDestination.home);
            },
            child: Scaffold(
              body: SafeArea(
                bottom: false,
                child: Column(
                  children: [
                    Material(
                      color: colors.surface,
                      child: Padding(
                        padding: const EdgeInsetsDirectional.fromSTEB(
                          20,
                          4,
                          4,
                          4,
                        ),
                        child: Row(
                          children: [
                            if (compactBrand)
                              Tooltip(
                                message: AppCopy.of(context, AppCopyKey.brand),
                                child: const Icon(
                                  Icons.route_rounded,
                                  size: 28,
                                ),
                              )
                            else
                              Text(
                                AppCopy.of(context, AppCopyKey.brand),
                                style: Theme.of(context).textTheme.titleLarge,
                              ),
                            const SizedBox(width: 12),
                            Expanded(child: widget.statusUtility),
                            PopupMenuButton<_AccountAction>(
                              key: const ValueKey('shell-account'),
                              tooltip: AppCopy.of(context, AppCopyKey.account),
                              icon: const Icon(Icons.account_circle_outlined),
                              onSelected: (action) {
                                switch (action) {
                                  case _AccountAction.refresh:
                                    widget.onRefresh();
                                    break;
                                  case _AccountAction.logout:
                                    widget.onLogout();
                                    break;
                                }
                              },
                              itemBuilder:
                                  (context) => [
                                    PopupMenuItem<_AccountAction>(
                                      enabled: false,
                                      child: Text(widget.accountName),
                                    ),
                                    PopupMenuItem(
                                      value: _AccountAction.refresh,
                                      child: Text(
                                        AppCopy.of(context, AppCopyKey.refresh),
                                      ),
                                    ),
                                    PopupMenuItem(
                                      value: _AccountAction.logout,
                                      child: Text(
                                        AppCopy.of(context, AppCopyKey.logout),
                                      ),
                                    ),
                                  ],
                            ),
                          ],
                        ),
                      ),
                    ),
                    const Divider(height: 1),
                    Expanded(
                      child: IndexedStack(
                        index: _selected.index,
                        children: [
                          TickerMode(
                            enabled: _selected == FieldDestination.home,
                            child: widget.homeBuilder(context),
                          ),
                          TickerMode(
                            enabled: _selected == FieldDestination.route,
                            child:
                                _routeOpened
                                    ? widget.routeBuilder(context)
                                    : const SizedBox.shrink(),
                          ),
                          TickerMode(
                            enabled: _selected == FieldDestination.custody,
                            child: widget.custody,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              bottomNavigationBar: Material(
                color: colors.surface,
                child: SafeArea(
                  top: false,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Divider(height: 1),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _destination(
                            context,
                            FieldDestination.home,
                            AppCopyKey.home,
                            Icons.home_outlined,
                            Icons.home_rounded,
                          ),
                          _destination(
                            context,
                            FieldDestination.route,
                            AppCopyKey.route,
                            Icons.route_outlined,
                            Icons.route_rounded,
                          ),
                          _destination(
                            context,
                            FieldDestination.custody,
                            AppCopyKey.custody,
                            Icons.inventory_2_outlined,
                            Icons.inventory_2_rounded,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _destination(
    BuildContext context,
    FieldDestination destination,
    AppCopyKey key,
    IconData icon,
    IconData selectedIcon,
  ) {
    final selected = _selected == destination;
    final colors = Theme.of(context).colorScheme;
    final label = AppCopy.of(context, key);
    return Expanded(
      child: Semantics(
        selected: selected,
        button: true,
        label: label,
        onTap: () => _select(destination),
        child: ExcludeSemantics(
          child: InkWell(
            key: ValueKey('shell-tab-${destination.name}'),
            onTap: () => _select(destination),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 76),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                child: Column(
                  children: [
                    Container(
                      width: 36,
                      height: 3,
                      decoration: BoxDecoration(
                        color: selected ? colors.primary : Colors.transparent,
                        borderRadius: const BorderRadius.vertical(
                          bottom: Radius.circular(3),
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Icon(
                      selected ? selectedIcon : icon,
                      color:
                          selected ? colors.primary : colors.onSurfaceVariant,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      label,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        fontWeight:
                            selected ? FontWeight.w800 : FontWeight.w500,
                        color:
                            selected ? colors.primary : colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
