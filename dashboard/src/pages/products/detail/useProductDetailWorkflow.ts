import type {
  ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import { useProductDetailState } from "@/pages/products/detail/useProductDetailState";

type Params = {
  detailSections:
    ProductDisplayPreferences["detailSections"];
};

export function useProductDetailWorkflow({
  detailSections,
}: Params) {
  const {
    detailProduct,
    setDetailProduct,
    openProductDetails,
    closeProductDetails,
  } = useProductDetailState();

  return {
    openProductDetails,
    identityScope: {
      setDetailProduct,
    },
    drawerProps: {
      product:
        detailProduct,
      detailSections,
      onClose:
        closeProductDetails,
    },
  };
}
