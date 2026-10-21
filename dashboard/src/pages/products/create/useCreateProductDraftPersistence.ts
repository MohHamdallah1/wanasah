import type {
  Dispatch,
  MutableRefObject,
  SetStateAction,
} from "react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import type {
  ProductDraft,
} from "@/pages/products/create/types";
import {
  emptyDraft,
} from "@/pages/products/create/useCreateProductState";

type Params = {
  draftStorageKey: string | null;
  draft: ProductDraft;
  setDraft: Dispatch<
    SetStateAction<ProductDraft>
  >;
  restoredDraftKey: MutableRefObject<
    string | null
  >;
  t: TFunction;
};

export function useCreateProductDraftPersistence({
  draftStorageKey,
  draft,
  setDraft,
  restoredDraftKey,
  t,
}: Params) {
  const skipScopeTransitionPersist = useRef(false);
  useLayoutEffect(() => {
    if (
      restoredDraftKey.current ===
      draftStorageKey
    ) {
      return;
    }

    restoredDraftKey.current = draftStorageKey;
    // Restore before paint and never persist the previous identity's render
    // into the new company/user key while setDraft is taking effect.
    skipScopeTransitionPersist.current = true;
    setDraft(emptyDraft);
    if (!draftStorageKey) return;
    try {
      const raw =
        sessionStorage.getItem(
          draftStorageKey
        );
      if (raw) {
        const parsed =
          JSON.parse(
            raw
          ) as Partial<ProductDraft>;
        const restored = {
          ...emptyDraft,
          ...parsed,
          family_mode:
            parsed.family_mode ??
            (parsed.family
              ? "existing"
              : "none"),
          family_id:
            parsed.family_id ??
            null,
        };
        setDraft(restored);
        if (
          restored.name ||
          restored.family ||
          restored.package_price ||
          restored.unit_price ||
          restored.unit_barcode ||
          restored.package_barcode
        ) {
          toast.message(
            t(
              "products.draftRestored"
            )
          );
        }
      }
    } catch {
      sessionStorage.removeItem(
        draftStorageKey
      );
    }
  }, [
    draftStorageKey,
    restoredDraftKey,
    setDraft,
    t,
  ]);

  useEffect(() => {
    if (skipScopeTransitionPersist.current) {
      skipScopeTransitionPersist.current = false;
      return;
    }
    if (
      !draftStorageKey ||
      restoredDraftKey.current !==
        draftStorageKey
    ) {
      return;
    }
    sessionStorage.setItem(
      draftStorageKey,
      JSON.stringify(draft)
    );
  }, [
    draft,
    draftStorageKey,
    restoredDraftKey,
  ]);
}
