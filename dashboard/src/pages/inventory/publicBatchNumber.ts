export const parsePublicBatchNumber = (
  value: unknown,
  invalid: () => never,
): string | null => {
  if (value === null) return null;
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value.length > 100
  ) {
    return invalid();
  }
  return value;
};

export const formatPublicBatchNumber = (
  value: string | null,
  noLotLabel: string,
): string => value ?? noLotLabel;
