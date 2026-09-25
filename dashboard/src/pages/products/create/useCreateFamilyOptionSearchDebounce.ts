import type {
  Dispatch,
  SetStateAction,
} from "react";
import {
  useEffect,
} from "react";

type Params = {
  createOpen: boolean;
  family: string;
  setFamilyOptionSearch: Dispatch<
    SetStateAction<string>
  >;
};

export function useCreateFamilyOptionSearchDebounce({
  createOpen,
  family,
  setFamilyOptionSearch,
}: Params) {
  useEffect(() => {
    if (!createOpen) {
      setFamilyOptionSearch("");
      return;
    }
    const timer =
      window.setTimeout(() => {
        setFamilyOptionSearch(
          family
            .trim()
            .slice(0, 100)
        );
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [
    createOpen,
    family,
    setFamilyOptionSearch,
  ]);
}
