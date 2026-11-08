import { LEDGER_OPERATION_REFERENCE_TYPES } from "./operationI18n";

/**
 * One reference-type catalog for BOTH ledger views. Server available_types
 * describes recorded types in the currently authorized warehouse, not every
 * historic producer or a restriction on what the ledger endpoint may query.
 *
 * Include new/legacy types returned by the authorized server and keep the
 * selected value representable while a different mode is loading. The backend
 * remains the authority for every read; option presence is not permission.
 */
export function ledgerMovementFilterTypes(
  availableTypes: readonly string[],
  selectedType: string,
): string[] {
  const valid = (type: unknown): type is string =>
    typeof type === "string" &&
    type.length > 0 && type.length <= 50 &&
    type.trim() === type && type !== "ALL" &&
    !/[\u0000-\u001f\u007f]/.test(type);
  return [...new Set([
    ...LEDGER_OPERATION_REFERENCE_TYPES,
    ...availableTypes,
    selectedType,
  ].filter(valid))];
}
