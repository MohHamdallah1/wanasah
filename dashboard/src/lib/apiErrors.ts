export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string' && error.message) return error.message;
  return typeof error === 'string' && error ? error : fallback;
}

export function apiErrorStatus(error: unknown): number | undefined {
  if (error && typeof error === 'object' && 'status' in error && typeof error.status === 'number') return error.status;
  return undefined;
}
