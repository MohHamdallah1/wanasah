export const loadProductsPage = () =>
  import("@/pages/products/ProductsPage");

export const preloadProductsPage = (): void => {
  void loadProductsPage();
};
