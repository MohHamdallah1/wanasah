import { apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { transferText } from "./i18n";
import { getErrorMessage } from "./utils";

export function transferCreateError(error: unknown): string {
  if ([403, 404].includes(apiErrorStatus(error) ?? 0)) {
    const requestId = apiErrorRequestId(error);
    return transferText("warehouseUnavailable") + (requestId ? ` (${requestId})` : "");
  }
  return getErrorMessage(error);
}
