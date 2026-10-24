import {
  useEffect,
  useState,
} from "react";

import {
  inspectProductImportFile,
  type ProductImportFilePreflightResult,
} from "@/pages/products/import/productImportFilePreflight";

type State = {
  loading: boolean;
  result: ProductImportFilePreflightResult | null;
};

export function useImportProductFilePreflight(
  file: File | null,
): State {
  const [
    state,
    setState,
  ] = useState<State>({
    loading: false,
    result: null,
  });

  useEffect(() => {
    let active = true;

    if (!file) {
      setState({
        loading: false,
        result: null,
      });
      return () => {
        active = false;
      };
    }

    setState({
      loading: true,
      result: null,
    });

    void inspectProductImportFile(
      file,
    ).then((result) => {
      if (!active) {
        return;
      }
      setState({
        loading: false,
        result,
      });
    });

    return () => {
      active = false;
    };
  }, [file]);

  return state;
}
