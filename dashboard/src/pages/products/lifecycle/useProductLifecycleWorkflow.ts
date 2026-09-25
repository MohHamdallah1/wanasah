import { useProductLifecycleState } from "@/pages/products/lifecycle/useProductLifecycleState";

type Params = {
  onChanged: () =>
    void | Promise<void>;
};

export function useProductLifecycleWorkflow({
  onChanged,
}: Params) {
  const {
    lifecycleProduct,
    openLifecycleManager,
    closeLifecycleManager,
  } = useProductLifecycleState();

  return {
    openLifecycleManager,
    managerProps: {
      product:
        lifecycleProduct,
      onClose:
        closeLifecycleManager,
      onChanged,
    },
  };
}
