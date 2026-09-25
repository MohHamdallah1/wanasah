import type {
  QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";

import type {
  ProductTrackingDefaults,
} from "@/pages/products/contracts";
import { createImportDownloads } from "@/pages/products/import/createImportDownloads";
import { createImportFileActions } from "@/pages/products/import/createImportFileActions";
import { deriveImportProductViewState } from "@/pages/products/import/helpers";
import { productImportSessionKey } from "@/pages/products/import/productImportSessionKey";
import { useImportProductCommands } from "@/pages/products/import/useImportProductCommands";
import { useImportProductPolling } from "@/pages/products/import/useImportProductPolling";
import { useImportProductState } from "@/pages/products/import/useImportProductState";
import { useImportProductUpload } from "@/pages/products/import/useImportProductUpload";
import { useImportSessionResume } from "@/pages/products/import/useImportSessionResume";
import { useImportTrackingDefaultsSync } from "@/pages/products/import/useImportTrackingDefaultsSync";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type I18nLookup = {
  exists: (key: string) => boolean;
};

type Params = {
  companyId: number | null;
  driverId: number | null;
  authFetch: AuthFetch;
  queryClient: QueryClient;
  t: TFunction;
  i18n: I18nLookup;
  online: boolean;
  trackingDefaults:
    | ProductTrackingDefaults
    | undefined;
  trackingDefaultsLoading: boolean;
  trackingDefaultsError: boolean;
  retryTrackingDefaults: () => void;
};

export function useImportProductWorkflow({
  companyId,
  driverId,
  authFetch,
  queryClient,
  t,
  i18n,
  online,
  trackingDefaults,
  trackingDefaultsLoading,
  trackingDefaultsError,
  retryTrackingDefaults,
}: Params) {
  const {
    importOpen,
    setImportOpen,
    importFile,
    setImportFile,
    importJobId,
    setImportJobId,
    importStatus,
    setImportStatus,
    importPollError,
    setImportPollError,
    mapping,
    setMapping,
    importPollKey,
    setImportPollKey,
    importLotControlMode,
    setImportLotControlMode,
    importExpiryControlMode,
    setImportExpiryControlMode,
    importTrackingExpanded,
    setImportTrackingExpanded,
    dragging,
    setDragging,
    fileRef,
  } = useImportProductState();

  const importSessionKey =
    productImportSessionKey(
      companyId,
      driverId
    );

  useImportSessionResume({
    importSessionKey,
    importJobId,
    setImportJobId,
    t,
  });

  useImportTrackingDefaultsSync({
    importOpen,
    importJobId,
    defaults:
      trackingDefaults,
    setImportLotControlMode,
    setImportExpiryControlMode,
  });

  const {
    progress,
    trackingUsesCompanyDefaults,
  } = deriveImportProductViewState(
    importStatus,
    trackingDefaults,
    importLotControlMode,
    importExpiryControlMode
  );

  const {
    importMutation,
    startImport,
  } = useImportProductUpload({
    importFile,
    importLotControlMode,
    importExpiryControlMode,
    companyId,
    driverId,
    authFetch,
    setImportJobId,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setImportStatus,
    setImportPollError,
    importSessionKey,
    t,
  });

  const {
    mappingMutation,
    retryImportMutation,
    updateMapping,
    submitMapping,
    retryImport,
  } = useImportProductCommands({
    importJobId,
    mapping,
    setMapping,
    authFetch,
    setImportPollError,
    setImportStatus,
    setImportPollKey,
    t,
  });

  const {
    retryPoll,
  } = useImportProductPolling({
    importJobId,
    importPollKey,
    setImportPollKey,
    authFetch,
    queryClient,
    t,
    isOnline: online,
    setImportPollError,
    setImportStatus,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setMapping,
  });

  const {
    chooseFile,
    resetImport,
    openImport,
    closeImport,
    expandImportTracking,
    resetImportTracking,
    completeImport,
  } = createImportFileActions({
    importSessionKey,
    importing:
      importMutation.isPending,
    trackingDefaultsQuery: {
      data:
        trackingDefaults,
    },
    fileRef,
    setImportOpen,
    setImportFile,
    setImportJobId,
    setImportStatus,
    setImportPollError,
    setMapping,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setImportTrackingExpanded,
    t,
  });

  const {
    downloadErrorReport,
    downloadTemplate,
  } = createImportDownloads({
    importJobId,
    authFetch,
    t,
    i18n,
  });

  return {
    openImport,
    identityScope: {
      setImportLotControlMode,
      setImportExpiryControlMode,
      setImportTrackingExpanded,
    },
    trackingMutationScope: {
      importJobId,
      setImportLotControlMode,
      setImportExpiryControlMode,
    },
    modalProps: {
      open: importOpen,
      importing:
        importMutation.isPending,
      online,
      jobId: importJobId,
      status: importStatus,
      pollError:
        importPollError,
      mapping,
      progress,
      file: importFile,
      dragging,
      lotControlMode:
        importLotControlMode,
      expiryControlMode:
        importExpiryControlMode,
      trackingDefaultsLoading,
      trackingDefaultsError,
      trackingUsesCompanyDefaults,
      trackingExpanded:
        importTrackingExpanded,
      mappingPending:
        mappingMutation.isPending,
      retryPending:
        retryImportMutation.isPending,
      fileRef,
      onClose:
        closeImport,
      onDownloadTemplate:
        downloadTemplate,
      onRetryTrackingDefaults:
        retryTrackingDefaults,
      onExpandTracking:
        expandImportTracking,
      onLotControlModeChange:
        setImportLotControlMode,
      onExpiryControlModeChange:
        setImportExpiryControlMode,
      onResetTracking:
        resetImportTracking,
      onChooseFile:
        chooseFile,
      onDraggingChange:
        setDragging,
      onStartImport:
        startImport,
      onRetryPoll:
        retryPoll,
      onMappingChange:
        updateMapping,
      onSubmitMapping:
        submitMapping,
      onDownloadErrorReport:
        downloadErrorReport,
      onResetImport:
        resetImport,
      onRetryImport:
        retryImport,
      onCompletedClose:
        completeImport,
    },
  };
}
