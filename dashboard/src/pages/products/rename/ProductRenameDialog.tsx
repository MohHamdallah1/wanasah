import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import {
  apiErrorCode,
  apiErrorMessage,
  isAmbiguousRequestError,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import {
  parseProductNameMutationResponse,
  type ProductNameMutationResponse,
  type SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct | null;
  companyId: number | null;
  driverId: number | null;
  onClose: () => void;
  onRenamed: (
    result: ProductNameMutationResponse,
  ) => void | Promise<void>;
};

type RenamePayload = {
  expected_version: number;
  name: string;
};

const validRenamePayload = (
  value: unknown,
): value is RenamePayload => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    Object.keys(row).length === 2 &&
    typeof row.expected_version === "number" &&
    Number.isSafeInteger(row.expected_version) &&
    row.expected_version > 0 &&
    typeof row.name === "string" &&
    row.name.trim().length > 0 &&
    row.name.trim().length <= 200
  );
};

const codedError = (
  code: string,
): Error & { code: string } => {
  const error = new Error(code) as Error & {
    code: string;
  };
  error.code = code;
  return error;
};

const retainPendingRename = (
  error: unknown,
): boolean => {
  const code = apiErrorCode(error);
  return (
    isAmbiguousRequestError(error) ||
    code === "DURABLE_OPERATION_PENDING" ||
    code === "DURABLE_OPERATION_CORRUPT" ||
    code ===
      "PRODUCT_NAME_MUTATION_RESPONSE_INVALID" ||
    code ===
      "PRODUCT_NAME_MUTATION_SCOPE_MISMATCH"
  );
};

export function ProductRenameDialog({
  product,
  companyId,
  driverId,
  onClose,
  onRenamed,
}: Props) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const isOnline = useNetworkStatus();

  const [name, setName] = useState("");
  const [expectedVersion, setExpectedVersion] =
    useState<number | null>(null);
  const [pending, setPending] = useState<
    DurableCommand<RenamePayload> | null
  >(null);
  const [pendingBlocked, setPendingBlocked] =
    useState(false);
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] =
    useState<string | null>(null);
  const inputRef =
    useRef<HTMLInputElement | null>(null);

  const scope = useMemo(() => {
    if (
      product === null ||
      companyId === null ||
      driverId === null
    ) {
      return null;
    }
    return durableScope(
      companyId,
      driverId,
      "catalog-product-name-update-v1",
      product.id,
    );
  }, [
    companyId,
    driverId,
    product,
  ]);

  useEffect(() => {
    let cancelled = false;

    setPending(null);
    setPendingBlocked(false);
    setBusy(false);
    setFieldError(null);

    if (!product) {
      setName("");
      setExpectedVersion(null);
      return () => {
        cancelled = true;
      };
    }

    setName(product.name);
    setExpectedVersion(product.version);

    if (!scope) {
      setPendingBlocked(true);
      return () => {
        cancelled = true;
      };
    }

    void (async () => {
      try {
        const stored =
          await readDurableCommand<unknown>(
            scope,
          );
        if (cancelled || !stored) {
          return;
        }
        if (
          !validRenamePayload(stored.payload)
        ) {
          throw codedError(
            "DURABLE_OPERATION_CORRUPT",
          );
        }
        const restored: DurableCommand<RenamePayload> = {
          requestId: stored.requestId,
          payload: stored.payload,
          createdAt: stored.createdAt,
        };
        setPending(restored);
        setName(restored.payload.name);
        setExpectedVersion(
          restored.payload.expected_version,
        );
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPendingBlocked(true);
        toast.error(
          apiErrorMessage(
            error,
            t("products.rename.errors.saveFailed"),
          ),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    product,
    scope,
    t,
  ]);

  if (!product) {
    return null;
  }

  const cleanName = name.trim();
  const unchanged =
    pending === null &&
    cleanName === product.name;

  const save = async () => {
    if (
      busy ||
      !scope ||
      !isOnline ||
      pendingBlocked
    ) {
      return;
    }

    if (!pending && !cleanName) {
      setFieldError(
        t("products.rename.errors.required"),
      );
      window.requestAnimationFrame(
        () => inputRef.current?.focus(),
      );
      return;
    }
    if (!pending && unchanged) {
      setFieldError(
        t("products.rename.errors.unchanged"),
      );
      return;
    }

    const freshPayload: RenamePayload = {
      expected_version:
        expectedVersion ?? product.version,
      name: cleanName,
    };

    setBusy(true);
    try {
      const command =
        pending ??
        (await getOrCreateDurableCommand(
          scope,
          freshPayload,
        ));
      setPending(command);

      const result =
        parseProductNameMutationResponse(
          await authFetch(
            `/catalog/variants/${product.id}/name`,
            {
              method: "PATCH",
              body: JSON.stringify({
                request_id: command.requestId,
                ...command.payload,
              }),
            },
          ),
        );

      if (
        result.product_variant_id !==
        product.id
      ) {
        throw codedError(
          "PRODUCT_NAME_MUTATION_SCOPE_MISMATCH",
        );
      }

      completeDurableOperation(
        scope,
        command.requestId,
      );
      setPending(null);
      setPendingBlocked(false);
      setFieldError(null);

      await queryClient.invalidateQueries({
        queryKey: ["simple-products"],
      });

      toast.success(
        t("products.rename.saved"),
      );
      await onRenamed(result);
    } catch (error) {
      const code = apiErrorCode(error);
      if (
        code === "DURABLE_OPERATION_CORRUPT"
      ) {
        setPendingBlocked(true);
      }

      if (!retainPendingRename(error)) {
        abandonDurableOperation(scope);
        setPending(null);
        setPendingBlocked(false);
      }

      if (
        code === "VARIANT_VERSION_CONFLICT"
      ) {
        await queryClient.invalidateQueries({
          queryKey: ["simple-products"],
        });
      }

      toast.error(
        apiErrorMessage(
          error,
          t("products.rename.errors.saveFailed"),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  const inputLocked =
    busy ||
    pending !== null ||
    pendingBlocked;

  return (
    <Modal
      isOpen={product !== null}
      onClose={() => {
        if (!busy) {
          onClose();
        }
      }}
      title={t("products.rename.title")}
      maxWidth="max-w-lg"
      footer={
        <>
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="px-4 py-2 text-sm font-bold text-slate-600 disabled:opacity-40"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            disabled={
              busy ||
              !isOnline ||
              pendingBlocked ||
              (!pending &&
                (!cleanName || unchanged))
            }
            onClick={() => void save()}
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-40"
          >
            {pending
              ? t("products.rename.retry")
              : t("products.rename.save")}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="rounded-2xl bg-slate-50 p-3 text-xs font-bold leading-6 text-slate-600">
          {t("products.rename.description")}
        </p>

        <label className="block text-xs font-black text-slate-600">
          {t("products.rename.label")}
          <input
            ref={inputRef}
            value={name}
            maxLength={200}
            disabled={inputLocked}
            onChange={(event) => {
              setName(event.target.value);
              if (fieldError) {
                setFieldError(null);
              }
            }}
            aria-invalid={
              fieldError ? "true" : undefined
            }
            aria-describedby={
              fieldError
                ? "product-rename-error"
                : undefined
            }
            className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none disabled:opacity-50"
          />
        </label>

        {fieldError ? (
          <p
            id="product-rename-error"
            role="alert"
            className="text-xs font-bold text-rose-700"
          >
            {fieldError}
          </p>
        ) : null}

        {pending ? (
          <p className="rounded-xl bg-amber-50 p-3 text-[11px] font-semibold leading-5 text-amber-900">
            {t("products.rename.pendingRetry")}
          </p>
        ) : pendingBlocked ? (
          <p className="rounded-xl bg-rose-50 p-3 text-[11px] font-semibold leading-5 text-rose-900">
            {t("products.rename.pendingBlocked")}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
