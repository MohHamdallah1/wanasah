import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useTenantIdentity } from "@/features/tenantIdentity/useTenantIdentity";
import { dispatchUiText, type DispatchUiKey } from "@/features/dispatch/dispatchUiText";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Shop, Zone } from "@/types/dispatch";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardPaste,
  FileDown,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import * as XLSX from "xlsx";
import Papa from "papaparse";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";

const scopedImportDraftKey = (scope: string) => `wanasah:dispatch:shop-import:v2:${scope}`;
const MAX_IMPORT_ROWS = 10_000;
const MAX_MONEY = 999_999_999.999;

interface ShopBulkImportModalProps {
  isOpen: boolean;
  actorScope: string | null;
  session: DashboardSession;
  onClose: () => void;
  zones: Zone[];
  existingShops: Shop[];
  onSuccess?: () => void;
}

interface ParsedShop {
  _id: string;
  name: string;
  phone: string;
  mapLink: string;
  owner: string;
  initialDebt: string;
}

interface DuplicateCandidate {
  key: string;
  shop?: Shop;
  rowNumber?: number;
}

interface ValidatedShop extends ParsedShop {
  errors: string[];
  duplicateCandidate: DuplicateCandidate | null;
}

interface DraftPayload {
  actorScope: string;
  zoneId: string;
  data: ParsedShop[];
}

const cellText = (value: unknown): string =>
  value === null || value === undefined ? "" : String(value).trim();

const normalizeName = (value: string): string => value.trim().toLowerCase();
const normalizeLink = (value: string): string => value.trim().toLowerCase();
const normalizePhone = (value: string): string =>
  value.trim().replace(/\.0$/, "");

const pairKey = (a: string, b: string): string =>
  a && b ? `${a}\u001f${b}` : "";

const hasValidMoney = (value: string): boolean => {
  const normalized = value.trim().replace(",", ".");
  if (!/^\d+(?:\.\d{1,3})?$/.test(normalized)) return false;
  const amount = Number(normalized);
  return Number.isFinite(amount) && amount >= 0 && amount <= MAX_MONEY;
};

const normalizeDraft = (
  value: unknown,
  expectedActorScope: string
): DraftPayload | null => {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;

  if (
    record.actorScope !== expectedActorScope ||
    typeof record.zoneId !== "string" ||
    !Array.isArray(record.data) ||
    record.data.length === 0 ||
    record.data.length > MAX_IMPORT_ROWS
  ) {
    return null;
  }

  const data: ParsedShop[] = [];
  for (const raw of record.data) {
    if (typeof raw !== "object" || raw === null) return null;
    const row = raw as Record<string, unknown>;
    data.push({
      _id:
        typeof row._id === "string" && row._id
          ? row._id
          : crypto.randomUUID(),
      name: cellText(row.name),
      phone: cellText(row.phone),
      mapLink: cellText(row.mapLink),
      owner: cellText(row.owner),
      initialDebt: cellText(row.initialDebt) || "0",
    });
  }

  return {
    actorScope: expectedActorScope,
    zoneId: record.zoneId,
    data,
  };
};

export function ShopBulkImportModal({
  isOpen,
  actorScope,
  session,
  onClose,
  zones,
  existingShops,
  onSuccess,
}: ShopBulkImportModalProps) {
  const authenticatedFetch = useAuthFetch();
  const { i18n } = useTranslation();
  const currency = useTenantIdentity().data?.currency_code;
  const text = (key: DispatchUiKey, values: Record<string, string | number> = {}) =>
    dispatchUiText(i18n.language, key, values);
  const [step, setStep] = useState<1 | 2>(1);
  const [selectedZoneId, setSelectedZoneId] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [gridData, setGridData] = useState<ParsedShop[]>([]);
  const [fileName, setFileName] = useState("");
  const [hasDraft, setHasDraft] = useState(false);
  const [conflictRow, setConflictRow] = useState<ValidatedShop | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const draftKey = actorScope ? scopedImportDraftKey(actorScope) : null;
  const readerRef = useRef<FileReader | null>(null);
  const latest = useRef({ actorScope, isOpen, session });
  latest.current = { actorScope, isOpen, session };
  const admitted = () => Boolean(actorScope && latest.current.actorScope === actorScope &&
    latest.current.isOpen && isDashboardSessionCurrent(session));

  useEffect(() => {
    if (!isOpen) {
      readerRef.current?.abort();
      readerRef.current = null;
      setConflictRow(null); setStep(1); setPasteText(""); setGridData([]);
      setSelectedZoneId(""); setFileName("");
    }
    return () => { readerRef.current?.abort(); readerRef.current = null; };
  }, [actorScope, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const raw = draftKey && admitted() ? localStorage.getItem(draftKey) : null;
    if (!raw || !actorScope) {
      setHasDraft(false);
      return;
    }

    try {
      const draft = normalizeDraft(JSON.parse(raw), actorScope);
      if (!draft) {
        draftKey && localStorage.removeItem(draftKey);
        setHasDraft(false);
        return;
      }
      setHasDraft(true);
    } catch {
      draftKey && localStorage.removeItem(draftKey);
      setHasDraft(false);
    }
  }, [actorScope, draftKey, isOpen]);

  useEffect(() => {
    if (
      selectedZoneId &&
      !zones.some((zone) => zone.id === selectedZoneId)
    ) {
      setSelectedZoneId("");
    }
  }, [selectedZoneId, zones]);

  useEffect(() => {
    if (
      !actorScope || !draftKey || !admitted() ||
      step !== 2 ||
      gridData.length === 0 ||
      !zones.some((zone) => zone.id === selectedZoneId)
    ) {
      return;
    }

    const draft: DraftPayload = {
      actorScope,
      zoneId: selectedZoneId,
      data: gridData,
    };
    localStorage.setItem(draftKey, JSON.stringify(draft));
    setHasDraft(true);
  }, [actorScope, draftKey, gridData, selectedZoneId, step, zones]);

  const clearDraft = () => {
    draftKey && localStorage.removeItem(draftKey);
    setHasDraft(false);
  };

  const loadDraft = () => {
    if (!actorScope || !admitted()) {
      toast.error(text("importBadScope"));
      return;
    }

    const raw = draftKey && admitted() ? localStorage.getItem(draftKey) : null;
    if (!raw) return;

    try {
      const draft = normalizeDraft(JSON.parse(raw), actorScope);
      if (
        !draft ||
        !zones.some((zone) => zone.id === draft.zoneId)
      ) {
        clearDraft();
        toast.error(
          text("importDraftInvalid")
        );
        return;
      }

      setSelectedZoneId(draft.zoneId);
      setGridData(draft.data);
      setStep(2);
      toast.success(text("importDraftRecovered"));
    } catch {
      clearDraft();
      toast.error(text("importDraftCorrupt"));
    }
  };

  const handleDownloadTemplate = () => {
    const headers = [
      `${text("importName")} ${text("importHeaderRequired")}`,
      `${text("importPhone")} ${text("importHeaderOptional")}`,
      `${text("importMap")} ${text("importHeaderOptional")}`,
      `${text("importOwner")} ${text("importHeaderOptional")}`,
      text("importOpeningDebt"),
    ];
    const worksheet = XLSX.utils.aoa_to_sheet([headers]);
    worksheet["!cols"] = [
      { wch: 28 },
      { wch: 22 },
      { wch: 45 },
      { wch: 28 },
      { wch: 18 },
    ];
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, text("importTemplateSheet"));
    XLSX.writeFile(workbook, text("importTemplateFile"));
  };

  const processRawData = (data: unknown[][]) => {
    const cleanedData = data.filter(
      (row) =>
        Array.isArray(row) &&
        row.length > 0 &&
        row.some((cell) => cellText(cell) !== "")
    );

    if (cleanedData.length === 0) {
      toast.error(text("importEmpty"));
      return;
    }

    const firstCell = cellText(cleanedData[0]?.[0]);
    const startIndex = firstCell.includes("اسم") || /^shop\s*name\b/i.test(firstCell) ? 1 : 0;
    const actualData = cleanedData.slice(startIndex);

    if (actualData.length === 0) {
      toast.error(text("importNoData"));
      return;
    }
    if (actualData.length > MAX_IMPORT_ROWS) {
      toast.error(
        text("importTooMany", { count: MAX_IMPORT_ROWS })
      );
      return;
    }

    const mappedData: ParsedShop[] = actualData.map((row) => ({
      _id: crypto.randomUUID(),
      name: cellText(row[0]),
      phone: normalizePhone(cellText(row[1])),
      mapLink: cellText(row[2]),
      owner: cellText(row[3]),
      initialDebt: cellText(row[4]).replace(",", ".") || "0",
    }));

    setGridData(mappedData);
    setStep(2);
  };

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!selectedZoneId) {
      if (fileInputRef.current) fileInputRef.current.value = "";
      toast.error(text("importSelectZone"));
      return;
    }

    setFileName(file.name.slice(0, 255));

    const reader = new FileReader();
    readerRef.current?.abort();
    readerRef.current = reader;
    reader.onload = (loadEvent) => {
      if (readerRef.current !== reader || !admitted() || !zones.some(zone => zone.id === selectedZoneId)) return;
      try {
        const result = loadEvent.target?.result;
        if (!(result instanceof ArrayBuffer)) {
          throw new Error(text("importReadFile"));
        }

        const workbook = XLSX.read(result, { type: "array" });
        const sheetName = workbook.SheetNames[0];
        if (!sheetName) {
          throw new Error(text("importReadSheet"));
        }

        const worksheet = workbook.Sheets[sheetName];
        const data = XLSX.utils.sheet_to_json<unknown[]>(worksheet, {
          header: 1,
          raw: false,
          defval: "",
        });
        processRawData(data);
      } catch (error: unknown) {
        if (admitted()) toast.error(text("importReadFile"));
      }
    };
    reader.onerror = () => { if (admitted()) toast.error(text("importReadFile")); };
    reader.readAsArrayBuffer(file);

    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handlePasteSubmit = () => {
    if (!selectedZoneId) {
      toast.error(text("importSelectZone"));
      return;
    }
    if (!pasteText.trim()) {
      toast.error(text("importNeedPaste"));
      return;
    }

    Papa.parse<string[]>(pasteText, {
      delimiter: "\t",
      complete: (results) => { if (admitted()) processRawData(results.data); },
    });
  };

  const updateCell = (
    id: string,
    field: keyof Omit<ParsedShop, "_id">,
    value: string
  ) => {
    setGridData((prev) =>
      prev.map((row) => (row._id === id ? { ...row, [field]: value } : row))
    );
  };

  const removeRow = (id: string) => {
    setGridData((prev) => prev.filter((row) => row._id !== id));
    setConflictRow((prev) => (prev?._id === id ? null : prev));
  };

  const validatedRows = useMemo<ValidatedShop[]>(() => {
    const phoneIndex = new Map<string, DuplicateCandidate>();
    const namePhoneIndex = new Map<string, DuplicateCandidate>();
    const nameLinkIndex = new Map<string, DuplicateCandidate>();
    const phoneLinkIndex = new Map<string, DuplicateCandidate>();

    const registerCandidate = (
      candidate: DuplicateCandidate,
      name: string,
      phone: string,
      link: string
    ) => {
      if (phone && !phoneIndex.has(phone)) {
        phoneIndex.set(phone, candidate);
      }

      const namePhone = pairKey(name, phone);
      const nameLink = pairKey(name, link);
      const phoneLink = pairKey(phone, link);

      if (namePhone && !namePhoneIndex.has(namePhone)) {
        namePhoneIndex.set(namePhone, candidate);
      }
      if (nameLink && !nameLinkIndex.has(nameLink)) {
        nameLinkIndex.set(nameLink, candidate);
      }
      if (phoneLink && !phoneLinkIndex.has(phoneLink)) {
        phoneLinkIndex.set(phoneLink, candidate);
      }
    };

    existingShops.forEach((shop) => {
      registerCandidate(
        { key: `db:${shop.id}`, shop },
        normalizeName(shop.name),
        normalizePhone(shop.phone || ""),
        normalizeLink(shop.mapLink || "")
      );
    });

    return gridData.map((row, index) => {
      const errors: string[] = [];
      const name = normalizeName(row.name);
      const phone = normalizePhone(row.phone);
      const link = normalizeLink(row.mapLink);
      const owner = row.owner.trim();
      const money = row.initialDebt.trim().replace(",", ".");

      if (name.length < 2) {
        errors.push(text("importNeedName"));
      }
      if (row.name.trim().length > 150) {
        errors.push(text("importNameLong"));
      }
      if (owner.length > 100) {
        errors.push(text("importOwnerLong"));
      }
      if (phone.length > 20) {
        errors.push(text("importPhoneLong"));
      }
      if (row.mapLink.trim().length > 500) {
        errors.push(text("importLinkLong"));
      }
      if (!hasValidMoney(money)) {
        errors.push(
          text("importMoneyInvalid")
        );
      }

      const duplicateCandidate =
        (phone ? phoneIndex.get(phone) : undefined) ||
        namePhoneIndex.get(pairKey(name, phone)) ||
        nameLinkIndex.get(pairKey(name, link)) ||
        phoneLinkIndex.get(pairKey(phone, link)) ||
        null;

      if (duplicateCandidate) {
        if (duplicateCandidate.shop) {
          errors.push(text("importDuplicateServer"));
        } else if (duplicateCandidate.rowNumber) {
          errors.push(text("importDuplicateRow", { count: duplicateCandidate.rowNumber }));
        }
      }

      if (!duplicateCandidate) {
        registerCandidate(
          { key: `row:${row._id}`, rowNumber: index + 1 },
          name,
          phone,
          link
        );
      }

      return {
        ...row,
        phone,
        initialDebt: money,
        errors,
        duplicateCandidate,
      };
    });
  }, [existingShops, gridData, i18n.language]);

  const stats = useMemo(() => {
    const invalid = validatedRows.filter(
      (row) => row.errors.length > 0
    ).length;
    return {
      total: validatedRows.length,
      valid: validatedRows.length - invalid,
      invalid,
    };
  }, [validatedRows]);

  const handleClose = () => {
    if (conflictRow) return;
    onClose();
    setStep(1);
    setPasteText("");
    setGridData([]);
    setSelectedZoneId("");
    setFileName("");
  };

  const handleBulkImport = async () => {
    if (!currency) { toast.error(text("importCurrencyPending")); return; }
    if (!actorScope || !admitted()) {
      toast.error(text("importBadScope"));
      return;
    }
    if (!zones.some((zone) => zone.id === selectedZoneId)) {
      toast.error(text("importNoZone"));
      return;
    }
    if (stats.invalid > 0) {
      toast.error(text("importCorrectErrors"));
      return;
    }
    if (
      validatedRows.length === 0 ||
      validatedRows.length > MAX_IMPORT_ROWS
    ) {
      toast.error(text("importBadCount"));
      return;
    }

    const payload = {
      zoneId: Number(selectedZoneId),
      fileName: (fileName || text("importPaste")).slice(0, 255),
      shops: validatedRows.map((row, index) => ({
        name: row.name.trim(),
        phone: row.phone,
        mapLink: row.mapLink.trim(),
        owner: row.owner.trim(),
        initialDebt: Number(row.initialDebt),
        sequence: index + 1,
      })),
    };

    const toastId = toast.loading(
      text("importUploading")
    );

    try {
      await authenticatedFetch(
        "/dispatch/shops/bulk_import",
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      if (!admitted()) { toast.dismiss(toastId); return; }
      toast.success(
        text("importSuccess"),
        { id: toastId }
      );
      clearDraft();
      handleClose();
      onSuccess?.();
    } catch (error: unknown) {
      if (!admitted()) { toast.dismiss(toastId); return; }
      toast.error(text("importError", { reason: text("importUnknown") }), { id: toastId });
    }
  };

  // Revoke/logout must remove private Shop data without a visible exit animation.
  if (!isOpen || !admitted()) return null;

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        title={text("importTitle")}
        maxWidth={step === 1 ? "max-w-4xl" : "max-w-6xl"}
      >
        {step === 1 && (
          <div className="space-y-6" dir={i18n.dir()}>
            {hasDraft && (
              <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl flex items-center justify-between mb-4">
                <div>
                  <h3 className="font-bold text-amber-800 text-sm">
                    {text("importHasDraft")}
                  </h3>
                  <p className="text-xs text-amber-700 mt-1">
                    {text("importDraftDescription")}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      clearDraft();
                      toast.info(text("importDraftDeleted"));
                    }}
                    className="px-3 py-2 bg-white text-red-500 font-bold text-sm rounded-lg hover:bg-red-50 shadow-sm transition-colors"
                    title={text("importDeleteDraft")}
                    aria-label={text("importDeleteDraft")}
                  >
                    🗑️
                  </button>
                  <button
                    onClick={loadDraft}
                    className="px-4 py-2 bg-amber-500 text-white font-bold text-sm rounded-lg hover:bg-amber-600 shadow-sm transition-colors"
                  >
                    {text("importRestoreDraft")} 📝
                  </button>
                </div>
              </div>
            )}

            <div className="bg-slate-50 p-5 rounded-xl border border-slate-200">
              <CustomSelect
                label={text("importZone")}
                options={zones.map((zone) => ({
                  id: zone.id,
                  label: zone.name,
                }))}
                value={selectedZoneId}
                onChange={(value) => { if (value === selectedZoneId) return; readerRef.current?.abort(); readerRef.current = null; setSelectedZoneId(value); setGridData([]); setStep(1); setFileName(""); }}
                placeholder={text("importZonePlaceholder")}
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-6">
              <div className="border border-slate-200 rounded-xl p-6 flex flex-col items-center justify-center gap-4 bg-white hover:border-[#1e87bb] transition-colors">
                <div className="text-center">
                  <h3 className="font-bold text-slate-800 text-lg">
                    {text("importFile")}
                  </h3>
                  <p className="text-xs text-slate-500 mt-1">
                    {text("importFileHelp")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleDownloadTemplate}
                  className="text-[#1e87bb] text-xs font-bold flex items-center gap-1 hover:underline bg-blue-50 px-3 py-1.5 rounded-lg"
                >
                  <FileDown className="w-4 h-4" /> {text("importDownload")}
                </button>
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileUpload}
                  className="hidden"
                  accept=".xlsx,.xls,.csv"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="w-full mt-2 min-h-11 py-3 rounded-xl bg-emerald-50 text-emerald-600 font-bold border border-emerald-200 hover:bg-emerald-100 transition-colors flex items-center justify-center gap-2"
                >
                  <Upload className="w-5 h-5" /> {text("importUpload")}
                </button>
              </div>

              <div className="border border-slate-200 rounded-xl p-6 flex flex-col gap-3 bg-white hover:border-[#1e87bb] transition-colors">
                <div className="text-center">
                  <h3 className="font-bold text-slate-800 text-lg">
                    {text("importPaste")}
                  </h3>
                  <p className="text-xs text-slate-500 mt-1">
                    {text("importPasteHelp")}
                  </p>
                </div>
                <textarea
                  value={pasteText}
                  onChange={(event) => setPasteText(event.target.value)}
                  placeholder={text("importPastePlaceholder")}
                  aria-label={text("importPaste")}
                  className="w-full h-24 rounded-xl border border-slate-200 p-3 text-sm focus:ring-2 focus:ring-[#1e87bb]/20 outline-none resize-none"
                  dir={i18n.dir()}
                />
                <button
                  type="button"
                  onClick={handlePasteSubmit}
                  className="w-full py-2.5 rounded-xl bg-[#1e87bb] text-white font-bold hover:bg-[#156a94] transition-colors flex items-center justify-center gap-2"
                >
                  <ClipboardPaste className="w-5 h-5" /> {text("importReadPaste")}
                </button>
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-50 p-3 sm:p-4 rounded-xl border border-slate-200">
              <div className="flex flex-wrap gap-4">
                <div className="flex flex-col">
                  <span className="text-xs text-slate-500">{text("importTotal")}</span>
                  <span className="font-bold text-slate-800">
                    {stats.total}
                  </span>
                </div>
                <div className="w-px h-8 bg-slate-200" />
                <div className="flex flex-col">
                  <span className="text-xs text-slate-500">{text("importReady")}</span>
                  <span className="font-bold text-emerald-600 flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {stats.valid}
                  </span>
                </div>
                <div className="w-px h-8 bg-slate-200" />
                <div className="flex flex-col">
                  <span className="text-xs text-slate-500">{text("importInvalid")}</span>
                  <span
                    className={`font-bold flex items-center gap-1 ${
                      stats.invalid > 0
                        ? "text-red-500"
                        : "text-slate-400"
                    }`}
                  >
                    <AlertCircle className="w-3.5 h-3.5" />
                    {stats.invalid}
                  </span>
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="px-4 py-2 bg-white border border-slate-200 rounded-lg text-sm font-bold text-slate-600 hover:bg-slate-50"
                >
                  {text("importBack")}
                </button>
                <button
                  disabled={stats.invalid > 0 || stats.total === 0 || !currency}
                  type="button"
                  onClick={handleBulkImport}
                  className="px-6 py-2 bg-[#1e87bb] text-white rounded-lg text-sm font-bold hover:bg-[#156a94] flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  {text("importSubmit")} <Save className="w-4 h-4" />
                </button>
              </div>
            </div>

            <p role="status" className="text-xs font-semibold text-slate-600">
              {currency ? text("importCurrencyNotice", { code: currency }) : text("importCurrencyPending")}
            </p>
            <div className="max-h-[50vh] overflow-auto rounded-xl border border-slate-200">
              <table className="w-full min-w-[920px] text-sm text-start">
                <thead className="bg-slate-100 sticky top-0 z-10 shadow-sm">
                  <tr>
                    <th className="p-3 text-slate-600 font-bold w-12 text-center">
                      #
                    </th>
                    <th className="p-3 text-slate-600 font-bold w-1/4">
                      {text("importName")} <span className="text-red-500">*</span>
                    </th>
                    <th className="p-3 text-slate-600 font-bold w-1/5">
                      {text("importPhone")}
                    </th>
                    <th className="p-3 text-slate-600 font-bold">
                      {text("importMap")}
                    </th>
                    <th className="p-3 text-slate-600 font-bold">
                      {text("importOwner")}
                    </th>
                    <th className="p-3 text-slate-600 font-bold w-24">
                      {text("importOpeningDebt")}
                    </th>
                    <th className="p-3 w-12" />
                  </tr>
                </thead>

                <tbody className="divide-y divide-slate-100">
                  {validatedRows.map((row, index) => {
                    const tooltip = row.errors.join("\n");
                    const dbConflict = row.duplicateCandidate?.shop;

                    return (
                      <tr
                        key={row._id}
                        onClick={() =>
                          dbConflict ? setConflictRow(row) : undefined
                        }
                        className={`transition-colors ${
                          dbConflict
                            ? "bg-amber-50 cursor-pointer border-y border-amber-200 hover:bg-amber-100"
                            : row.errors.length > 0
                              ? "bg-red-50/50"
                              : "hover:bg-slate-50"
                        }`}
                        title={tooltip}
                      >
                        <td className="p-2 text-center text-slate-500 font-bold relative group">
                          {index + 1}
                          {row.errors.length > 0 && (
                            <span id={`import-errors-${row._id}`} role="alert" className="sr-only">
                              {row.errors.join(". ")}
                            </span>
                          )}
                          {dbConflict && (
                            <button type="button" onClick={() => setConflictRow(row)}
                              aria-label={text("importConflictTitle")}
                              className="min-h-9 rounded-lg border border-amber-400 px-2 text-xs text-amber-900 focus-visible:ring-2">
                              <AlertCircle aria-hidden="true" className="h-4 w-4" />
                            </button>
                          )}
                          {row.errors.length > 0 && (
                            <>
                              <AlertCircle
                                className={`w-3.5 h-3.5 absolute top-1/2 right-1 -translate-y-1/2 cursor-help ${
                                  dbConflict
                                    ? "text-amber-500"
                                    : "text-red-500"
                                }`}
                              />
                              <div className="absolute right-6 top-1/2 -translate-y-1/2 w-max max-w-xs bg-slate-800 text-white text-xs p-2 rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 pointer-events-none shadow-xl whitespace-pre-wrap text-start leading-relaxed">
                                {tooltip}
                              </div>
                            </>
                          )}
                        </td>

                        <td className="p-2">
                          <input
                            aria-label={`${text("importName")} ${index + 1}`}
                            aria-invalid={row.errors.length > 0}
                            aria-describedby={row.errors.length ? `import-errors-${row._id}` : undefined}
                            value={row.name}
                            maxLength={150}
                            onChange={(event) =>
                              updateCell(row._id, "name", event.target.value)
                            }
                            placeholder={text("importRequired")}
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                            disabled={Boolean(dbConflict)}
                          />
                        </td>

                        <td className="p-2">
                          <input
                            aria-label={`${text("importPhone")} ${index + 1}`}
                            value={row.phone}
                            maxLength={20}
                            onChange={(event) =>
                              updateCell(
                                row._id,
                                "phone",
                                event.target.value
                              )
                            }
                            placeholder={text("importOptional")}
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                            dir="ltr"
                            disabled={Boolean(dbConflict)}
                          />
                        </td>

                        <td className="p-2">
                          <input
                            aria-label={`${text("importMap")} ${index + 1}`}
                            value={row.mapLink}
                            maxLength={500}
                            onChange={(event) =>
                              updateCell(
                                row._id,
                                "mapLink",
                                event.target.value
                              )
                            }
                            placeholder={text("importOptional")}
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                            disabled={Boolean(dbConflict)}
                          />
                        </td>

                        <td className="p-2">
                          <input
                            aria-label={`${text("importOwner")} ${index + 1}`}
                            value={row.owner}
                            maxLength={100}
                            onChange={(event) =>
                              updateCell(
                                row._id,
                                "owner",
                                event.target.value
                              )
                            }
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                            disabled={Boolean(dbConflict)}
                          />
                        </td>

                        <td className="p-2">
                          <input
                            aria-label={`${text("importOpeningDebt")} ${index + 1}`}
                            aria-invalid={row.errors.length > 0}
                            type="number"
                            min="0"
                            max={MAX_MONEY}
                            step="0.001"
                            value={row.initialDebt}
                            onChange={(event) =>
                              updateCell(
                                row._id,
                                "initialDebt",
                                event.target.value
                              )
                            }
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-center focus:outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                            disabled={Boolean(dbConflict)}
                          />
                        </td>

                        <td className="p-2 text-center">
                          <button
                            type="button"
                            aria-label={text("importDeleteRow", { count: index + 1 })}
                            onClick={(event) => {
                              event.stopPropagation();
                              removeRow(row._id);
                            }}
                            className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {gridData.length === 0 && (
                <div className="p-8 text-center text-slate-400">
                  {text("importNoRows")}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      {conflictRow?.duplicateCandidate?.shop && (
        <Modal
          isOpen
          onClose={() => setConflictRow(null)}
          title={text("importConflictTitle")}
        >
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm">
                <h4 className="font-bold text-slate-400 text-xs mb-3">
                  {text("importExisting")}
                </h4>
                <p className="font-bold text-lg text-slate-800">
                  {conflictRow.duplicateCandidate.shop.name}
                </p>
                <p className="text-sm text-slate-600 mt-1">
                  {text("importOwner")}:{" "}
                  <span className="font-bold">
                    {conflictRow.duplicateCandidate.shop.owner || text("importNoOwner")}
                  </span>
                </p>
                <p className="text-xs font-bold text-[#1e87bb] mt-2 bg-blue-50 w-fit px-2 py-1 rounded-md">
                  {text("zone")}:{" "}
                  {zones.find(
                    (zone) =>
                      zone.id ===
                      conflictRow.duplicateCandidate?.shop?.zoneId
                  )?.name || text("shopNoZone")}
                </p>
                <p
                  className="text-sm mt-3 text-slate-500 font-medium"
                  dir="ltr"
                >
                  {conflictRow.duplicateCandidate.shop.phone || text("importNoPhone")}
                </p>
              </div>

              <div className="bg-white p-5 rounded-2xl border border-amber-200 shadow-sm">
                <h4 className="font-bold text-amber-500 text-xs mb-3">
                  {text("importIncoming")}
                </h4>
                <p className="font-bold text-lg text-slate-800">
                  {conflictRow.name}
                </p>
                <p className="text-sm text-slate-600 mt-1">
                  {text("importOwner")}:{" "}
                  <span className="font-bold">
                    {conflictRow.owner || text("importNoOwner")}
                  </span>
                </p>
                <p className="text-xs font-bold text-amber-600 mt-2 bg-amber-50 w-fit px-2 py-1 rounded-md">
                  {text("importTargetZone")}:{" "}
                  {zones.find((zone) => zone.id === selectedZoneId)?.name || ""}
                </p>
                <p
                  className="text-sm mt-3 text-slate-500 font-medium"
                  dir="ltr"
                >
                  {conflictRow.phone || text("importNoPhone")}
                </p>
              </div>
            </div>

            <div className="bg-red-50 border border-red-200 rounded-xl p-3">
              <p className="text-xs text-red-700 font-bold">
                {text("importConflictReason")}
              </p>
            </div>

            <button type="button"
              onClick={() => {
                removeRow(conflictRow._id);
                setConflictRow(null);
              }}
              className="w-full bg-slate-100 text-slate-700 py-3 rounded-xl font-bold hover:bg-slate-200 transition-colors border border-slate-300"
            >
              {text("importConflictRemove")} 🗑️
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
