import type {
  ProductFamily,
} from "@/pages/products/contracts";
import type {
  ProductDraft,
} from "@/pages/products/create/types";

export type CreateProductFamilyIntentError =
  | "EXISTING_FAMILY_REQUIRED"
  | "NEW_FAMILY_NAME_REQUIRED";

export type CreateProductFamilyIntent =
  | {
      ok: true;
      family_id: number | null;
      family_name: string | null;
    }
  | {
      ok: false;
      error: CreateProductFamilyIntentError;
    };

const normalizedFamilyName = (
  value: string,
) =>
  value
    .trim()
    .toLocaleLowerCase();

export function resolveCreateProductFamilyIntent(
  draft: ProductDraft,
  familyOptions: ProductFamily[],
): CreateProductFamilyIntent {
  if (
    draft.family_mode === "none"
  ) {
    return {
      ok: true,
      family_id: null,
      family_name: null,
    };
  }

  if (
    draft.family_mode === "new"
  ) {
    const familyName =
      draft.family.trim();
    if (!familyName) {
      return {
        ok: false,
        error:
          "NEW_FAMILY_NAME_REQUIRED",
      };
    }
    return {
      ok: true,
      family_id: null,
      family_name: familyName,
    };
  }

  const selectedFamily =
    familyOptions.find(
      (item) =>
        item.id ===
          draft.family_id ||
        normalizedFamilyName(
          item.name,
        ) ===
          normalizedFamilyName(
            draft.family,
          ),
    );

  const familyId =
    draft.family_id ??
    selectedFamily?.id ??
    null;

  if (!familyId) {
    return {
      ok: false,
      error:
        "EXISTING_FAMILY_REQUIRED",
    };
  }

  return {
    ok: true,
    family_id: familyId,
    family_name: null,
  };
}
