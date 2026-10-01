import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useMutation } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { toast } from "sonner";

import { apiErrorCode, apiErrorMessage, apiErrorStatus } from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  fileFingerprint,
  getOrCreateDurableCommand,
} from "@/lib/durableOperations";
import { productDurableScope } from "@/pages/products/productDurableScope";
import { correctionRouteBlocked } from "@/pages/products/import/correctionRouteGate";
import type { ProductImportState } from "@/pages/products/contracts";

type AuthFetch = (path: string, options?: RequestInit) => Promise<unknown>;

type Params = {
  companyId: number | null;
  driverId: number | null;
  jobId: string | null;
  online: boolean;
  authFetch: AuthFetch;
  downloadCorrection: () => Promise<void>;
  setImportPollKey: Dispatch<SetStateAction<number>>;
  setImportStatus: Dispatch<SetStateAction<ProductImportState | null>>;
  t: TFunction;
};

type CorrectionAck = {
  job_id: string;
  status: "VALIDATING";
  corrected_rows: number;
  replayed: boolean;
};

function correctionAck(raw: unknown, jobId: string): CorrectionAck {
  const row = raw as Record<string, unknown> | null;
  if (
    !row || typeof row !== "object" || Array.isArray(row) ||
    row.job_id !== jobId ||
    row.status !== "VALIDATING" ||
    !Number.isInteger(row.corrected_rows) ||
    (row.corrected_rows as number) <= 0 ||
    typeof row.replayed !== "boolean"
  ) {
    throw new Error("PRODUCT_IMPORT_CORRECTION_RESPONSE_INVALID");
  }
  return row as CorrectionAck;
}

/** Same-job file correction. A pending upload owns one request UUID + file hash. */
export function useImportCorrection({
  companyId,
  driverId,
  jobId,
  online,
  authFetch,
  downloadCorrection,
  setImportPollKey,
  setImportStatus,
  t,
}: Params) {
  const [selected, setSelected] = useState<{ jobId: string; file: File } | null>(null);
  const [downloading, setDownloading] = useState(false);
  const currentJobRef = useRef(jobId);
  const fileRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    currentJobRef.current = jobId;
  }, [jobId]);

  const file = selected?.jobId === jobId ? selected.file : null;

  const chooseFile = (next: File | null) => {
    if (!jobId || !next || upload.isPending) return;
    if (!/\.(xlsx|csv)$/i.test(next.name)) {
      toast.error(t("products.errors.unsupportedFile"));
      return;
    }
    setSelected({ jobId, file: next });
  };

  const download = async () => {
    if (!jobId || !online || downloading) return;
    const requestedJob = jobId;
    setDownloading(true);
    try {
      // A resumed different import cannot download an obsolete job artifact.
      await downloadCorrection();
      if (requestedJob === currentJobRef.current) {
        toast.success(t("products.correction.downloaded"));
      }
    } catch (error) {
      if (requestedJob === currentJobRef.current) {
        toast.error(apiErrorMessage(error, t("products.correction.downloadFailed")));
      }
    } finally {
      setDownloading(false);
    }
  };

  const upload = useMutation({
    mutationFn: async () => {
      if (!jobId || !file || !online) {
        throw new Error("PRODUCT_IMPORT_CORRECTION_FILE_REQUIRED");
      }
      if (correctionRouteBlocked(companyId, driverId, jobId, "file")) {
        throw new Error("PRODUCT_IMPORT_CORRECTION_ROUTE_CONFLICT");
      }
      const scope = productDurableScope(
        companyId, driverId, "product-import-correction", jobId,
      );
      const fingerprint = await fileFingerprint(file);
      // No file bytes or tenant data are put in localStorage. A lost response
      // must be retried with the same file AND the same saved request identity.
      const command = await getOrCreateDurableCommand(scope, {
        jobId,
        fingerprint,
        name: file.name,
        size: file.size,
      });
      const form = new FormData();
      form.append("request_id", command.requestId);
      form.append("file", file);
      try {
        const ack = correctionAck(
          await authFetch(`/simple-products/imports/${jobId}/correction`, {
            method: "POST",
            body: form,
          }),
          jobId,
        );
        return { ack, scope, requestId: command.requestId, requestedJob: jobId };
      } catch (error) {
        // Only a deterministic server rejection known to make zero writes may
        // release the local pending operation for the user to fix and resubmit.
        if (
          [413, 422].includes(apiErrorStatus(error) ?? -1) ||
          (apiErrorStatus(error) === 410 &&
            apiErrorCode(error) === "PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED")
        ) {
          // Expiry is confirmed before applying changes. Retain the pending
          // command on ambiguous responses, but free this proven zero-write
          // request so it cannot lock the job in the local UI forever.
          abandonDurableOperation(scope);
          if (apiErrorStatus(error) === 410 &&
              currentJobRef.current === jobId) {
            setSelected(null);
            if (fileRef.current) fileRef.current.value = "";
          }
        }
        throw error;
      }
    },
    onSuccess: ({ scope, requestId, requestedJob, ack }) => {
      completeDurableOperation(scope, requestId);
      if (requestedJob !== currentJobRef.current) return;
      setSelected(null);
      if (fileRef.current) fileRef.current.value = "";
      setImportStatus((current) => current && current.job_id === requestedJob
        ? { ...current, status: ack.status }
        : current);
      setImportPollKey((current) => current + 1);
      toast.success(
        t("products.correction.accepted", { count: ack.corrected_rows }),
      );
    },
    onError: (error) => {
      toast.error(apiErrorMessage(error, t("products.correction.uploadFailed")));
    },
  });

  return {
    correctionFile: file,
    correctionFileRef: fileRef,
    chooseCorrectionFile: chooseFile,
    downloadCorrection: () => { void download(); },
    downloadingCorrection: downloading,
    uploadCorrection: () => { if (!upload.isPending) upload.mutate(); },
    uploadingCorrection: upload.isPending,
  };
}
