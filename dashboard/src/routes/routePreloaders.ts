export const loadOperationsDashboard = () =>
  import("@/pages/OperationsDashboard");

export const loadDispatchBoard = () =>
  import("@/pages/DispatchBoard");

export const loadInventoryPage = () =>
  import("@/pages/inventory/InventoryPage");

export const loadProductsPage = () =>
  import("@/pages/products/ProductsPage");

export const loadRepresentativesVehiclesPage = () =>
  import("@/pages/representatives-vehicles/RepresentativesVehiclesPage");

export const loadCommercialRulesDashboard = () =>
  import("@/pages/CommercialRulesDashboard");

export const loadSalesReturnsDashboard = () =>
  import("@/pages/SalesReturnsDashboard");

const fireAndForget = (loader: () => Promise<unknown>): void => {
  void loader();
};

export const preloadOperationsDashboard = (): void =>
  fireAndForget(loadOperationsDashboard);

export const preloadDispatchBoard = (): void =>
  fireAndForget(loadDispatchBoard);

export const preloadInventoryPage = (): void =>
  fireAndForget(loadInventoryPage);

export const preloadProductsPage = (): void =>
  fireAndForget(loadProductsPage);

export const preloadRepresentativesVehiclesPage = (): void =>
  fireAndForget(loadRepresentativesVehiclesPage);

export const preloadCommercialRulesDashboard = (): void =>
  fireAndForget(loadCommercialRulesDashboard);

export const preloadSalesReturnsDashboard = (): void =>
  fireAndForget(loadSalesReturnsDashboard);
