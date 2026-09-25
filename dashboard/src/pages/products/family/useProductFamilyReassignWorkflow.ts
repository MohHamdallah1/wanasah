import { useProductFamilyReassignState } from "@/pages/products/family/useProductFamilyReassignState";

type Params = {
  companyId: number | null;
  driverId: number | null;
};

export function useProductFamilyReassignWorkflow({
  companyId,
  driverId,
}: Params) {
  const {
    familyReassignProduct,
    setFamilyReassignProduct,
    openFamilyReassign,
    closeFamilyReassign,
  } =
    useProductFamilyReassignState();

  return {
    openFamilyReassign,
    identityScope: {
      setFamilyReassignProduct,
    },
    dialogProps: {
      product:
        familyReassignProduct,
      companyId,
      driverId,
      onClose:
        closeFamilyReassign,
      onReassigned:
        closeFamilyReassign,
    },
  };
}
