import 'dart:ui';

import 'package:flutter/material.dart';

import '../../l10n/generated/app_localizations.dart';
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
              extendBody: true,
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
                                message: AppLocalizations.of(context).brand,
                                child: const Icon(
                                  Icons.route_rounded,
                                  size: 28,
                                ),
                              )
                            else
                              Text(
                                AppLocalizations.of(context).brand,
                                style: Theme.of(context).textTheme.titleLarge,
                              ),
                            const SizedBox(width: 12),
                            Expanded(child: widget.statusUtility),
                            PopupMenuButton<_AccountAction>(
                              key: const ValueKey('shell-account'),
                              tooltip: AppLocalizations.of(context).account,
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
                                        AppLocalizations.of(context).refresh,
                                      ),
                                    ),
                                    PopupMenuItem(
                                      value: _AccountAction.logout,
                                      child: Text(
                                        AppLocalizations.of(context).logout,
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
              bottomNavigationBar: SafeArea(
                top: false,
                minimum: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(30),
                  child: BackdropFilter(
                    filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: colors.surface.withValues(alpha: 0.82),
                        borderRadius: BorderRadius.circular(30),
                        border: Border.all(
                          color: colors.outlineVariant.withValues(alpha: 0.65),
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: colors.shadow.withValues(alpha: 0.10),
                            blurRadius: 24,
                            offset: const Offset(0, 10),
                          ),
                        ],
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 6,
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.center,
                          children: [
                            _destination(
                              context,
                              FieldDestination.route,
                              AppLocalizations.of(context).route,
                              Icons.route_outlined,
                              Icons.route_rounded,
                            ),
                            _destination(
                              context,
                              FieldDestination.home,
                              AppLocalizations.of(context).home,
                              Icons.home_outlined,
                              Icons.home_rounded,
                              emphasized: true,
                            ),
                            _destination(
                              context,
                              FieldDestination.custody,
                              AppLocalizations.of(context).custody,
                              Icons.inventory_2_outlined,
                              Icons.inventory_2_rounded,
                            ),
                          ],
                        ),
                      ),
                    ),
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
    String label,
    IconData icon,
    IconData selectedIcon, {
    bool emphasized = false,
  }) {
    final selected = _selected == destination;
    final colors = Theme.of(context).colorScheme;
    final background =
        selected
            ? colors.primary.withValues(alpha: emphasized ? 1 : 0.11)
            : emphasized
            ? colors.surfaceContainerHighest.withValues(alpha: 0.72)
            : Colors.transparent;
    final foreground =
        selected && emphasized
            ? colors.onPrimary
            : selected
            ? colors.primary
            : colors.onSurfaceVariant;

    return Expanded(
      child: Semantics(
        selected: selected,
        button: true,
        label: label,
        onTap: () => _select(destination),
        child: ExcludeSemantics(
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: emphasized ? 4 : 2,
              vertical: emphasized ? 0 : 4,
            ),
            child: InkWell(
              key: ValueKey('shell-tab-${destination.name}'),
              borderRadius: BorderRadius.circular(emphasized ? 24 : 20),
              onTap: () => _select(destination),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                curve: Curves.easeOutCubic,
                constraints: const BoxConstraints(minHeight: 60),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
                decoration: BoxDecoration(
                  color: background,
                  borderRadius: BorderRadius.circular(emphasized ? 24 : 20),
                  border:
                      emphasized && !selected
                          ? Border.all(
                            color: colors.outlineVariant.withValues(
                              alpha: 0.55,
                            ),
                          )
                          : null,
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    AnimatedScale(
                      duration: const Duration(milliseconds: 180),
                      scale: selected ? 1.08 : 1,
                      child: Icon(
                        selected ? selectedIcon : icon,
                        color: foreground,
                        size: emphasized ? 27 : 24,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      label,
                      maxLines: 1,
                      overflow: TextOverflow.fade,
                      softWrap: false,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        fontSize: emphasized ? 13 : 12.5,
                        fontWeight:
                            selected ? FontWeight.w800 : FontWeight.w600,
                        color: foreground,
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
