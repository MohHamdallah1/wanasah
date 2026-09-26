import type {
  RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  ProductImportState,
  ProductTrackingMode,
} from "@/pages/products/contracts";
import type {
  ImportMappingField,
} from "@/pages/products/import/importFields";
import { ImportProductMappingPanel } from "@/pages/products/import/ImportProductMappingPanel";
import { ImportProductStartPanel } from "@/pages/products/import/ImportProductStartPanel";
import { ImportProductStatusPanel } from "@/pages/products/import/ImportProductStatusPanel";
import { ImportStageRail } from "@/pages/products/import/ImportStageRail";

type Props = {
  open: boolean;
  importing: boolean;
  online: boolean;
  jobId: string | null;
  status: ProductImportState | null;
  pollError: string | null;
  mapping: Record<string, string>;
  progress: number;
  file: File | null;
  dragging: boolean;
  lotControlMode: ProductTrackingMode | null;
  expiryControlMode: ProductTrackingMode | null;
  trackingDefaultsLoading: boolean;
  trackingDefaultsError: boolean;
  trackingUsesCompanyDefaults: boolean;
  trackingExpanded: boolean;
  mappingPending: boolean;
  retryPending: boolean;
  fileRef: RefObject<HTMLInputElement | null>;
  onClose: () => void;
  onDownloadTemplate: () => void;
  onRetryTrackingDefaults: () => void;
  onExpandTracking: () => void;
  onLotControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onResetTracking: () => void;
  onChooseFile: (
    file: File | null,
  ) => void;
  onDraggingChange: (
    value: boolean,
  ) => void;
  onStartImport: () => void;
  onRetryPoll: () => void;
  onMappingChange: (
    field: ImportMappingField,
    value: string,
  ) => void;
  onSubmitMapping: () => void;
  onDownloadErrorReport: () => void;
  onResetImport: () => void;
  onRetryImport: () => void;
  onCompletedClose: () => void;
};

export function ImportProductModal({
  open,
  importing,
  online,
  jobId,
  status,
  pollError,
  mapping,
  progress,
  file,
  dragging,
  lotControlMode,
  expiryControlMode,
  trackingDefaultsLoading,
  trackingDefaultsError,
  trackingUsesCompanyDefaults,
  trackingExpanded,
  mappingPending,
  retryPending,
  fileRef,
  onClose,
  onDownloadTemplate,
  onRetryTrackingDefaults,
  onExpandTracking,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetTracking,
  onChooseFile,
  onDraggingChange,
  onStartImport,
  onRetryPoll,
  onMappingChange,
  onSubmitMapping,
  onDownloadErrorReport,
  onResetImport,
  onRetryImport,
  onCompletedClose,
}: Props) {
  const { t } = useTranslation();

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={t(
        "products.importTitle",
      )}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-3">
        <ImportStageRail
          jobId={jobId}
          status={status}
        />

        {!jobId ? (
          <ImportProductStartPanel
            importing={importing}
            online={online}
            file={file}
            dragging={dragging}
            lotControlMode={
              lotControlMode
            }
            expiryControlMode={
              expiryControlMode
            }
            trackingDefaultsLoading={
              trackingDefaultsLoading
            }
            trackingDefaultsError={
              trackingDefaultsError
            }
            trackingUsesCompanyDefaults={
              trackingUsesCompanyDefaults
            }
            trackingExpanded={
              trackingExpanded
            }
            fileRef={fileRef}
            onDownloadTemplate={
              onDownloadTemplate
            }
            onRetryTrackingDefaults={
              onRetryTrackingDefaults
            }
            onExpandTracking={
              onExpandTracking
            }
            onLotControlModeChange={
              onLotControlModeChange
            }
            onExpiryControlModeChange={
              onExpiryControlModeChange
            }
            onResetTracking={
              onResetTracking
            }
            onChooseFile={
              onChooseFile
            }
            onDraggingChange={
              onDraggingChange
            }
            onStartImport={
              onStartImport
            }
          />
        ) : status?.status ===
          "NEEDS_MAPPING" ? (
          <ImportProductMappingPanel
            detectedHeaders={
              status.detected_headers
            }
            mapping={mapping}
            mappingPending={
              mappingPending
            }
            online={online}
            onMappingChange={
              onMappingChange
            }
            onSubmitMapping={
              onSubmitMapping
            }
          />
        ) : (
          <ImportProductStatusPanel
            status={status}
            pollError={pollError}
            progress={progress}
            online={online}
            retryPending={
              retryPending
            }
            onRetryPoll={
              onRetryPoll
            }
            onDownloadErrorReport={
              onDownloadErrorReport
            }
            onResetImport={
              onResetImport
            }
            onRetryImport={
              onRetryImport
            }
            onCompletedClose={
              onCompletedClose
            }
          />
        )}
      </div>
    </Modal>
  );
}
