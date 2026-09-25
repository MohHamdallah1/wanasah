import {
  useState,
} from "react";

export function useProductFamiliesState() {
  const [
    familiesOpen,
    setFamiliesOpen,
  ] = useState(false);

  const openFamilies = () =>
    setFamiliesOpen(true);

  const closeFamilies = () =>
    setFamiliesOpen(false);

  return {
    familiesOpen,
    setFamiliesOpen,
    openFamilies,
    closeFamilies,
  };
}
