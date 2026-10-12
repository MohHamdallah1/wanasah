type Params = {
  isCompanyOwner: boolean;
  can: (code: string) => boolean;
  canAny: (code: string) => boolean;
};

export function deriveProductsCapabilities({
  isCompanyOwner,
  can,
  canAny,
}: Params) {
  const canManageCatalog =
    isCompanyOwner ||
    canAny("catalog.manage");
  const canViewPricing =
    isCompanyOwner ||
    canAny("pricing.view");
  const canPublishCatalog =
    isCompanyOwner ||
    canAny("catalog.publish");
  const canManagePricing =
    isCompanyOwner ||
    canAny("pricing.manage");
  const canCreateSimpleProduct =
    isCompanyOwner ||
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
      isCompanyOwner ||
      can("catalog.retire") ||
      can("catalog.restore") ||
      can("catalog.archive") ||
      can("catalog.hold"),
  };
}
