import { apiErrorCode, isAmbiguousRequestError } from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
} from "@/lib/durableOperations";

export type StocktakeDurableIdentity = {
  companyId: number;
  backofficeUserId: number;
};

type ExecuteArgs<TPayload, TResult> = {
  identity: StocktakeDurableIdentity;
  operation: string;
  target: string | number;
  payload: TPayload;
  send: (body: TPayload & { request_id: string }) => Promise<TResult>;
};

export async function executeStocktakeDurableCommand<TPayload extends object, TResult>({
  identity,
  operation,
  target,
  payload,
  send,
}: ExecuteArgs<TPayload, TResult>): Promise<TResult> {
  const scope = durableScope(
    identity.companyId,
    identity.backofficeUserId,
    `stocktake-${operation}-v1`,
    target,
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
      code === "DURABLE_OPERATION_PENDING" ||
      code === "STOCKTAKE_RESPONSE_INVALID";
    if (!ambiguous) abandonDurableOperation(scope);
    throw error;
  }
}
