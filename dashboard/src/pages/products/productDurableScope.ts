import {
  durableScope,
} from "@/lib/durableOperations";

export function productDurableScope(
  companyId: number | null,
  driverId: number | null,
  operation: string,
  target: string | number = "default",
) {
  if (
    !companyId ||
    !driverId
  ) {
    throw new Error(
      "IDENTITY_NOT_READY"
    );
  }
  return durableScope(
    companyId,
    driverId,
    operation,
    target
  );
}
