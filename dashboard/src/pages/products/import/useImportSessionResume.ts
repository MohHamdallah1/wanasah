import type {
  Dispatch,
  SetStateAction,
} from "react";
import {
  useEffect,
} from "react";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

type Params = {
  importSessionKey: string | null;
  importJobId: string | null;
  setImportJobId: Dispatch<
    SetStateAction<string | null>
  >;
  t: TFunction;
};

export function useImportSessionResume({
  importSessionKey,
  importJobId,
  setImportJobId,
  t,
}: Params) {
  useEffect(() => {
    if (!importSessionKey) {
      return;
    }
    const stored =
      sessionStorage.getItem(
        importSessionKey
      );
    if (
      stored &&
      !importJobId
    ) {
      setImportJobId(stored);
      toast.message(
        t(
          "products.importResumed"
        )
      );
    }
  }, [
    importJobId,
    importSessionKey,
    setImportJobId,
    t,
  ]);
}
