/** Preserve an API error's safe reason without owning transport or authorization. */
export const getErrorMessage = (error: unknown): string =>
  error instanceof Error && error.message ? error.message : "";
