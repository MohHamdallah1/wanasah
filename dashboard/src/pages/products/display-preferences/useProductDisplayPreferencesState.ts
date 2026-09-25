import {
  useState,
} from "react";

import {
  readProductDisplayPreferences,
  type ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";

export function useProductDisplayPreferencesState() {
  const [
    displayPreferences,
    setDisplayPreferences,
  ] =
    useState<ProductDisplayPreferences>(
      () =>
        readProductDisplayPreferences(
          Number(
            localStorage.getItem(
              "company_id"
            )
          ),
          Number(
            localStorage.getItem(
              "driver_id"
            )
          )
        )
    );
  const [
    displayPreferencesOpen,
    setDisplayPreferencesOpen,
  ] = useState(false);

  const openDisplayPreferences =
    () => {
      setDisplayPreferencesOpen(
        true
      );
    };

  const closeDisplayPreferences =
    () => {
      setDisplayPreferencesOpen(
        false
      );
    };

  return {
    displayPreferences,
    setDisplayPreferences,
    displayPreferencesOpen,
    setDisplayPreferencesOpen,
    openDisplayPreferences,
    closeDisplayPreferences,
  };
}
