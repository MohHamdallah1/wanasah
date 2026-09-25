type Params = {
  isCompanyAdmin: boolean;
  can: (code: string) => boolean;
  canAny: (code: string) => boolean;
};

export function deriveProductsCapabilities({
  isCompanyAdmin,
  can,
  canAny,
}: Params) {
  const canManageCatalog =
    isCompanyAdmin ||
    canAny("catalog.manage");
  const canViewPricing =
    isCompanyAdmin ||
    canAny("pricing.view");
  const canPublishCatalog =
    isCompanyAdmin ||
    canAny("catalog.publish");
  const canManagePricing =
    isCompanyAdmin ||
    canAny("pricing.manage");
  const canCreateSimpleProduct =
    isCompanyAdmin ||
    (
      canManageCatalog &&
      canPublishCatalog &&
      canManagePricing
    );

  return {
    canManageCatalog,
    canViewPricing,
    canPublishCatalog,
    canManagePricing,
    canCreateSimpleProduct,
    canImportProducts:
      canCreateSimpleProduct,
    canManageFamilies:
      canManageCatalog,
    canEditSimplePrice:
      canManagePricing,
    canManageLifecycle:
      isCompanyAdmin ||
      can("catalog.retire") ||
      can("catalog.restore") ||
      can("catalog.archive") ||
      can("catalog.hold"),
  };
}
