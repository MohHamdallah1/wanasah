import type {
  Dispatch,
  RefObject,
  SetStateAction,
} from "react";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import type {
  ProductImportState,
  ProductTrackingDefaults,
  ProductTrackingMode,
} from "@/pages/products/contracts";

type Params = {
  importSessionKey: string | null;
  trackingDefaultsQuery: {
    data?: ProductTrackingDefaults;
  };
  fileRef: RefObject<HTMLInputElement | null>;
  setImportFile: Dispatch<
    SetStateAction<File | null>
  >;
  setImportJobId: Dispatch<
    SetStateAction<string | null>
  >;
  setImportStatus: Dispatch<
    SetStateAction<ProductImportState | null>
  >;
  setImportPollError: Dispatch<
    SetStateAction<string | null>
  >;
  setMapping: Dispatch<
    SetStateAction<Record<string, string>>
  >;
  setImportLotControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setImportExpiryControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setImportTrackingExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  t: TFunction;
};

export function createImportFileActions({
  importSessionKey,
  trackingDefaultsQuery,
  fileRef,
  setImportFile,
  setImportJobId,
  setImportStatus,
  setImportPollError,
  setMapping,
  setImportLotControlMode,
  setImportExpiryControlMode,
  setImportTrackingExpanded,
  t,
}: Params) {
  const chooseFile = (
    file: File | null
  ) => {
    if (!file) {
      return;
    }
    const lower =
      file.name.toLowerCase();
    if (
      !lower.endsWith(
        ".csv"
      ) &&
      !lower.endsWith(
        ".xlsx"
      )
    ) {
      toast.error(
        t(
          "products.errors.unsupportedFile"
        )
      );
      return;
    }

    setImportFile(file);
    setImportJobId(null);
    setImportStatus(null);
    setImportPollError(null);
    setMapping({});
    if (
      importSessionKey
    ) {
      sessionStorage.removeItem(
        importSessionKey
      );
    }
  };

  const resetImport =
    () => {
      setImportFile(null);
      setImportJobId(null);
      setImportStatus(null);
      setImportPollError(null);
      setMapping({});
      setImportLotControlMode(
        trackingDefaultsQuery.data
          ?.lot_control_mode ?? null
      );
      setImportExpiryControlMode(
        trackingDefaultsQuery.data
          ?.expiry_control_mode ?? null
      );
      setImportTrackingExpanded(false);
      if (importSessionKey) {
        sessionStorage.removeItem(
          importSessionKey
        );
      }
      if (fileRef.current) {
        fileRef.current.value =
          "";
      }
    };


  return {
    chooseFile,
    resetImport,
  };
}
