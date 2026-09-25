import { useProductRenameState } from "@/pages/products/rename/useProductRenameState";

type Params = {
  companyId: number | null;
  driverId: number | null;
};

export function useProductRenameWorkflow({
  companyId,
  driverId,
}: Params) {
  const {
    renameProduct,
    setRenameProduct,
    openRenameProduct,
    closeRenameProduct,
  } = useProductRenameState();

  return {
    openRenameProduct,
    identityScope: {
      setRenameProduct,
    },
    dialogProps: {
      product:
        renameProduct,
      companyId,
      driverId,
      onClose:
        closeRenameProduct,
      onRenamed:
        closeRenameProduct,
    },
  };
}
