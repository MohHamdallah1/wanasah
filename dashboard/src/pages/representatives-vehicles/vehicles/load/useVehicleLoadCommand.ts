import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorStatus, isAmbiguousRequestError } from "@/lib/apiErrors";
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";

import { mutateVehicleLoad } from "./api";
import type {
  VehicleLoadDirection,
  VehicleLoadMutationPayload,
  VehicleLoadMutationResult,
} from "./contracts";

type VehicleLoadWireCommand = {
  direction: VehicleLoadDirection;
  payload: VehicleLoadMutationPayload;
};

function vehicleLoadCommandScope(
  vehicleId: number,
  direction: VehicleLoadDirection,
): string {
  const companyId = Number(localStorage.getItem("company_id"));
  const principalId = Number(localStorage.getItem("principal_id"));
  if (
    !Number.isSafeInteger(companyId) ||
    companyId <= 0 ||
    !Number.isSafeInteger(principalId) ||
    principalId <= 0
  ) {
    throw Object.assign(new Error(), { code: "INVENTORY_ACCESS_SCOPE_MISMATCH" });
  }
  return durableScope(
    companyId,
    principalId,
    `vehicle-load-${direction.toLowerCase()}`,
    vehicleId,
  );
}

export function useVehicleLoadCommand(
  vehicleId: number,
  direction: VehicleLoadDirection,
) {
  const authFetch = useAuthFetch();
  const scope = useMemo(() => {
    try {
      return vehicleLoadCommandScope(vehicleId, direction);
    } catch {
      return null;
    }
  }, [direction, vehicleId]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  const active = useRef(new Set<string>());
  const [pending, setPending] =
    useState<DurableCommand<VehicleLoadWireCommand> | null>(null);
  const [busy, setBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<unknown>(null);

  useEffect(() => {
    let current = true;
    setPending(null);
    setRecoveryError(null);
    if (!scope) return () => { current = false; };
    void readDurableCommand<VehicleLoadWireCommand>(scope).then(
      (command) => {
        if (current) setPending(command);
      },
      (error) => {
        if (current) setRecoveryError(error);
      },
    );
    return () => {
      current = false;
    };
  }, [scope]);

  const execute = useCallback(
    async (
      payload?: VehicleLoadMutationPayload,
    ): Promise<VehicleLoadMutationResult | undefined> => {
      if (!scope || recoveryError) {
        throw recoveryError ??
          Object.assign(new Error(), { code: "INVENTORY_ACCESS_SCOPE_MISMATCH" });
      }
      if (active.current.has(scope)) return undefined;

      active.current.add(scope);
      setBusy(true);
      let command: DurableCommand<VehicleLoadWireCommand> | null = null;
      try {
        const wire = payload ? { direction, payload } : undefined;
        command = wire
          ? await getOrCreateDurableCommand(scope, wire)
          : await readDurableCommand<VehicleLoadWireCommand>(scope);
        if (!command) return undefined;
        if (scopeRef.current === scope) setPending(command);

        const result = await mutateVehicleLoad(
          authFetch,
          vehicleId,
          command.payload.direction,
          command.payload.payload,
          command.requestId,
        );
        completeDurableOperation(scope, command.requestId);
        if (scopeRef.current === scope) setPending(null);
        return result;
      } catch (error) {
        const status = apiErrorStatus(error);
        if (
          command &&
          status &&
          status >= 400 &&
          status < 500 &&
          !isAmbiguousRequestError(error)
        ) {
          completeDurableOperation(scope, command.requestId);
          if (scopeRef.current === scope) setPending(null);
        }
        throw error;
      } finally {
        active.current.delete(scope);
        if (scopeRef.current === scope) setBusy(false);
      }
    },
    [authFetch, direction, recoveryError, scope, vehicleId],
  );

  return {
    pending,
    busy,
    recoveryError,
    execute,
    retryPending: () => execute(),
  };
}
