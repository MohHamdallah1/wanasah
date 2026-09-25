import type {
  Dispatch,
  MutableRefObject,
  SetStateAction,
} from "react";
import {
  useEffect,
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
  useEffect(() => {
    if (!draftStorageKey) {
      return;
    }
    if (
      restoredDraftKey.current ===
      draftStorageKey
    ) {
      return;
    }

    restoredDraftKey.current =
      draftStorageKey;
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
