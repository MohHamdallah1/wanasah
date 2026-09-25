import {
  useRef,
  useState,
} from "react";

import type {
  ProductImportState,
  ProductTrackingMode,
} from "@/pages/products/contracts";

export function useImportProductState() {
  const [
    importOpen,
    setImportOpen,
  ] = useState(false);
  const [
    importFile,
    setImportFile,
  ] = useState<File | null>(
    null
  );
  const [
    importJobId,
    setImportJobId,
  ] = useState<string | null>(
    null
  );
  const [
    importStatus,
    setImportStatus,
  ] =
    useState<ProductImportState | null>(
      null
    );
  const [
    importPollError,
    setImportPollError,
  ] = useState<string | null>(
    null
  );
  const [
    mapping,
    setMapping,
  ] = useState<
    Record<string, string>
  >({});
  const [
    importPollKey,
    setImportPollKey,
  ] = useState(0);
  const [
    importLotControlMode,
    setImportLotControlMode,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    importExpiryControlMode,
    setImportExpiryControlMode,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    importTrackingExpanded,
    setImportTrackingExpanded,
  ] = useState(false);
  const [
    dragging,
    setDragging,
  ] = useState(false);
  const fileRef =
    useRef<HTMLInputElement | null>(
      null
    );

  return {
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
  };
}
