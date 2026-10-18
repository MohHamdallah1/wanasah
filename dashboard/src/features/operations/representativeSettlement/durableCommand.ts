import { apiErrorCode, isAmbiguousRequestError } from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
} from "@/lib/durableOperations";

const localIdentity = () => {
  const companyId = Number(localStorage.getItem("company_id"));
  const backofficeUserId = Number(localStorage.getItem("backoffice_user_id"));
  if (!Number.isSafeInteger(companyId) || companyId <= 0 ||
      !Number.isSafeInteger(backofficeUserId) || backofficeUserId <= 0) {
    const error = new Error("SETTLEMENT_DURABLE_IDENTITY_NOT_READY") as Error & { code: string };
    error.code = "SETTLEMENT_DURABLE_IDENTITY_NOT_READY";
    throw error;
  }
  return { companyId, backofficeUserId };
};

export async function executeRepresentativeSettlementCommand<TPayload extends object, TResult>({
  operation,
  sessionId,
  payload,
  send,
}: {
  operation: string;
  sessionId: number;
  payload: TPayload;
  send: (body: TPayload & { request_id: string }) => Promise<TResult>;
}): Promise<TResult> {
  const identity = localIdentity();
  const scope = durableScope(
    identity.companyId,
    identity.backofficeUserId,
    "representative-settlement-" + operation + "-v1",
    sessionId,
  );
  const command = await getOrCreateDurableCommand(scope, payload);
  try {
    const result = await send({
      request_id: command.requestId,
      ...command.payload,
    });
    completeDurableOperation(scope, command.requestId);
    return result;
  } catch (error) {
    const code = apiErrorCode(error);
    const ambiguous =
      isAmbiguousRequestError(error) ||
      code === "DURABLE_OPERATION_PENDING";
    if (!ambiguous) abandonDurableOperation(scope);
    throw error;
  }
}
