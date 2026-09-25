import { useProductFamiliesState } from "@/pages/products/family/useProductFamiliesState";

type Params = {
  companyId: number | null;
  driverId: number | null;
};

export function useProductFamiliesWorkflow({
  companyId,
  driverId,
}: Params) {
  const {
    familiesOpen,
    openFamilies,
    closeFamilies,
  } = useProductFamiliesState();

  return {
    openFamilies,
    managerProps: {
      isOpen:
        familiesOpen,
      companyId,
      driverId,
      onClose:
        closeFamilies,
    },
  };
}
