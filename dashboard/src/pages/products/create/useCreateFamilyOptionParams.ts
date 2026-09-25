import {
  useMemo,
} from "react";

export function useCreateFamilyOptionParams(
  familyOptionSearch: string,
) {
  return useMemo(
    () => {
      const value =
        new URLSearchParams({
          limit: "20",
        });
      if (familyOptionSearch) {
        value.set(
          "search",
          familyOptionSearch
        );
      }
      return value.toString();
    },
    [familyOptionSearch]
  );
}
