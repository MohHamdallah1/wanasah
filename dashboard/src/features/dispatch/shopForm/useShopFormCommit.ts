import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { toast } from "sonner";
import { apiErrorCode, apiErrorMessage, apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import {
  createPayload, createdShopVerified, financeReadback, findCreatedShopAfterUnknownWrite,
  metadataPayload, metadataVerified,
  ShopFormInputError, type ShopCreatePayload, type ShopFormState, type ShopFinanceReadback,
  type ShopMetadataPayload,
} from "./contract";
import { shopFormText, withSafeReference } from "./messages";

type AuthFetch = (path: string, options?: RequestInit) => Promise<unknown>;
export interface DuplicateShop {
  name: string;
  owner?: string | null;
  phone?: string | null;
  zone_name?: string | null;
}
export interface DuplicateShopWarning {
  shopData: DuplicateShop;
  payload: ShopCreatePayload;
}

type PendingVerification = {
  id: string | null;
  mode: "create" | "edit";
  payload: ShopCreatePayload | ShopMetadataPayload;
  /** Captured from an authorized GET BEFORE POST; never guessed afterwards. */
  baselineIds?: string[];
};

interface Args {
  open: boolean;
  editId: string | null;
  form: ShopFormState;
  language: string;
  session: DashboardSession;
  canViewFinances: boolean;
  busy: boolean;
  setBusy: Dispatch<SetStateAction<boolean>>;
  fetch: AuthFetch;
  onVerified: (shops: unknown, isCreate: boolean, zoneId: string) => void;
  onClose: () => void;
}

/** One Shop form commit boundary, never a finance-adjustment workflow. */
export function useShopFormCommit({
  open, editId, form, language, session, canViewFinances, busy, setBusy,
  fetch, onVerified, onClose,
}: Args) {
  const mounted = useRef(true);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const [finance, setFinance] = useState<ShopFinanceReadback | null>(null);
  const [financeLoading, setFinanceLoading] = useState(false);
  const [duplicate, setDuplicate] = useState<DuplicateShopWarning | null>(null);
  const [pending, setPending] = useState<PendingVerification | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const current = useCallback(
    (token: number) => mounted.current && generation.current === token &&
      isDashboardSessionCurrent(session),
    [session],
  );

  useEffect(() => {
    mounted.current = true;
    const reference = generation;
    return () => { mounted.current = false; reference.current++; };
  }, []);

  // The pending write must survive language and finance-visibility changes.
  // Reset only when the form identity or login session actually changes.
  useEffect(() => {
    generation.current++;
    setFinance(null);
    setFeedback(null);
    setDuplicate(null);
    setPending(null);
  }, [open, editId, session]);

  useEffect(() => {
    const token = generation.current;
    let active = true;
    setFinance(null);
    if (!open || !editId || !canViewFinances) {
      setFinanceLoading(false);
      return;
    }
    const controller = new AbortController();
    setFinanceLoading(true);
    void fetch("/dispatch/shops", { cache: "no-store", signal: controller.signal })
      .then(rows => {
        if (!active || !current(token)) return;
        const fresh = financeReadback(rows, editId);
        if (fresh) setFinance(fresh);
        else setFeedback(shopFormText(language, "financeRefreshFailed"));
      }).catch(() => {
        if (active && current(token)) setFeedback(shopFormText(language, "financeRefreshFailed"));
      }).finally(() => {
        if (active && current(token)) setFinanceLoading(false);
      });
    return () => { active = false; controller.abort(); };
    // A language change may re-read finance but never clears a pending mutation.
  }, [open, editId, canViewFinances, session, fetch, current, language]);

  const refreshAfterConflict = useCallback(async (token: number, id: string): Promise<void> => {
    // A rejected 409 is NOT success; refresh current finance without replacing
    // the operator's metadata form, and only if this principal is authorized.
    if (!canViewFinances) return;
    setFinance(null);
    try {
      const rows = await fetch("/dispatch/shops", { cache: "no-store" });
      if (current(token)) setFinance(financeReadback(rows, id));
    } catch {
      if (current(token)) setFinance(null);
    }
  }, [canViewFinances, fetch, current]);

  const finish = useCallback(async (token: number, verification: PendingVerification): Promise<boolean> => {
    try {
      const rows = await fetch("/dispatch/shops", { cache: "no-store" });
      if (!current(token)) return false;
      if (verification.mode === "create" && !verification.id) {
        // A new matching ID is not evidence that THIS request created it.
        // Another principal could have inserted identical metadata while our
        // POST never committed. Without a server-backed operation identity,
        // do not mark success, clear the draft or permit another POST.
        const possibleMatch = findCreatedShopAfterUnknownWrite(
          rows, verification.baselineIds ?? [], verification.payload as ShopCreatePayload,
        );
        setFeedback(shopFormText(language, possibleMatch ? "createUncorrelated" : "createNotFound"));
        return false;
      }
      const id = verification.id;
      const verified = Boolean(id) && (verification.mode === "create"
        ? createdShopVerified(rows, id!, verification.payload as ShopCreatePayload)
        : metadataVerified(rows, id!, verification.payload as ShopMetadataPayload));
      if (!verified) {
        setFeedback(shopFormText(language,
          verification.mode === "create" && !verification.id ? "createNotFound" : "readback"));
        return false;
      }
      setPending(null);
      onVerified(rows, verification.mode === "create", String(verification.payload.zoneId));
      onClose();
      toast.success(shopFormText(language, verification.mode === "create" ? "added" : "edited"));
      return true;
    } catch (error) {
      if (!current(token)) return false;
      if (apiErrorStatus(error) === 401 || apiErrorStatus(error) === 403) {
        setFinance(null);
        setFeedback(withSafeReference(shopFormText(language, "denied"),
          apiErrorRequestId(error), language));
      } else {
        setFeedback(withSafeReference(shopFormText(language, "readback"),
          apiErrorRequestId(error), language));
      }
      return false;
    }
  }, [fetch, current, language, onVerified, onClose]);

  const verify = useCallback(async (): Promise<boolean> => {
    if (!pending || inFlight.current || busy) return false;
    const token = generation.current;
    inFlight.current = true;
    setBusy(true);
    try {
      return await finish(token, pending); // GET only: never replay a possibly committed POST/PUT.
    } finally {
      inFlight.current = false;
      // The verified success closes the modal and invalidates generation.
      // inFlight serializes this hook, so release its shared busy flag even
      // after this form closes; never update an unmounted or logged-out session.
      if (mounted.current && isDashboardSessionCurrent(session)) setBusy(false);
    }
  }, [pending, busy, setBusy, finish, current, session]);

  const submit = useCallback(async (forcePayload?: ShopCreatePayload): Promise<boolean> => {
    if (busy || inFlight.current || pending || !open) return false;
    const token = generation.current;
    let create: ShopCreatePayload | undefined;
    let metadata: ShopMetadataPayload;
    try {
      metadata = metadataPayload(form);
      if (!editId) create = forcePayload ?? createPayload(form);
    } catch (error) {
      if (error instanceof ShopFormInputError) {
        const key = error.field === "money" ? "invalidMoney"
          : error.field === "phone" ? "phoneCannotClear" : "invalidMetadata";
        setFeedback(shopFormText(language, key));
        return false;
      }
      throw error;
    }
    inFlight.current = true;
    setBusy(true);
    setFeedback(null);
    const payload = editId ? metadata : create!;
    const mode: PendingVerification["mode"] = editId ? "edit" : "create";
    let baselineIds: string[] | undefined;
    let mutationStarted = false;
    try {
      if (!editId) {
        // A lost POST response contains no shop_id. A PRE-write authorized
        // membership snapshot is required to identify exactly one new match.
        // If offline here, NO mutation is attempted and no unknown guard is set.
        const before = await fetch("/dispatch/shops", { cache: "no-store" });
        if (!current(token)) return false;
        if (!Array.isArray(before) || !before.every(row =>
          row && typeof row === "object" && /^\d+$/.test(String((row as { id?: unknown }).id ?? "")))) {
          throw new Error("SHOP_FORM_PRECREATE_SNAPSHOT_INVALID");
        }
        baselineIds = before.map(row => String((row as { id: unknown }).id));
      }
      mutationStarted = true;
      const response = await fetch(editId ? `/dispatch/shops/${editId}` : "/dispatch/shops", {
        method: editId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      if (!current(token)) return false;
      const id = editId || parseCreatedId(response);
      const verification: PendingVerification = { id, mode, payload, baselineIds };
      setPending(verification); // lock repeat mutation until authorized GET verifies
      return await finish(token, verification);
    } catch (error) {
      if (!current(token)) return false;
      const status = apiErrorStatus(error);
      const code = apiErrorCode(error);
      if (!mutationStarted) {
        const denied = status === 401 || status === 403;
        const message = withSafeReference(shopFormText(language,
          denied ? "denied" : "beforeCreateFailed"), apiErrorRequestId(error), language);
        setFeedback(message);
        toast.error(message);
        return false; // definitively no POST; ordinary retry remains possible
      }
      if (!editId && status === 409 && !forcePayload) {
        const existing = readDuplicate(error);
        if (existing) {
          setDuplicate({ shopData: existing, payload: create! });
          return false;
        }
      }
      if (status === 409 && editId) {
        const key = code === "SHOP_FINANCIAL_STALE_FORM" ? "financialStale"
          : code === "SHOP_FINANCIAL_ACTION_REQUIRES_AUTHORITY" ? "financialAuthority"
            : "conflict";
        const fallback = shopFormText(language, key);
        const reason = code === "SHOP_FINANCIAL_STALE_FORM" ||
          code === "SHOP_FINANCIAL_ACTION_REQUIRES_AUTHORITY"
          ? fallback : apiErrorMessage(error, fallback);
        const message = withSafeReference(reason, apiErrorRequestId(error), language);
        setFeedback(message);
        toast.error(message);
        await refreshAfterConflict(token, editId);
      } else if (status === 409 || status === 400 || status === 404 || status === 422) {
        // Definitive rejection: do not strand the form behind an unknown-write guard.
        const key = status === 400 || status === 422 ? "invalidMetadata" : "conflict";
        // Safe, deterministic 4xx business reasons include archived Zone and
        // phone-unique rejections. Do not flatten them to a generic status.
        const reason = apiErrorMessage(error, shopFormText(language, key));
        const message = withSafeReference(reason, apiErrorRequestId(error), language);
        setFeedback(message);
        toast.error(message);
      } else if (status === 401 || status === 403) {
        setFinance(null);
        const message = withSafeReference(shopFormText(language, "denied"), apiErrorRequestId(error), language);
        setFeedback(message);
        toast.error(message);
      } else {
        // A timeout/5xx after send may have committed; no automatic replay.
        const message = withSafeReference(shopFormText(language, "unknown"), apiErrorRequestId(error), language);
        setFeedback(message);
        toast.error(message);
        setPending({ id: editId, mode, payload, baselineIds });
      }
      return false;
    } finally {
      inFlight.current = false;
      // The verified success closes the modal and invalidates generation.
      // inFlight serializes this hook, so release its shared busy flag even
      // after this form closes; never update an unmounted or logged-out session.
      if (mounted.current && isDashboardSessionCurrent(session)) setBusy(false);
    }
  }, [busy, pending, open, form, editId, fetch, current, language,
    setBusy, finish, refreshAfterConflict, session]);

  const save = useCallback(() => submit(), [submit]);
  const confirmDuplicate = useCallback(async (): Promise<boolean> => {
    if (!duplicate) return false;
    setDuplicate(null);
    return submit({ ...duplicate.payload, force_save: true });
  }, [duplicate, submit]);
  return {
    save, verify, confirmDuplicate, duplicate, clearDuplicate: () => setDuplicate(null),
    finance, financeLoading, feedback, needsVerification: pending !== null,
  };
}

function parseCreatedId(response: unknown): string {
  const raw = response && typeof response === "object"
    ? (response as { shop_id?: unknown }).shop_id : undefined;
  if ((typeof raw !== "string" && typeof raw !== "number") ||
    !/^\d+$/.test(String(raw)) || Number(raw) <= 0) {
    throw new Error("SHOP_FORM_CREATE_RESPONSE_INVALID");
  }
  return String(raw);
}
function readDuplicate(error: unknown): DuplicateShop | null {
  if (!error || typeof error !== "object") return null;
  const data = (error as { data?: unknown }).data;
  if (!data || typeof data !== "object") return null;
  const record = data as { is_duplicate?: unknown; existing_shop?: unknown };
  if (record.is_duplicate !== true || !record.existing_shop ||
    typeof record.existing_shop !== "object") return null;
  const shop = record.existing_shop as Record<string, unknown>;
  if (typeof shop.name !== "string") return null;
  return {
    name: shop.name,
    owner: typeof shop.owner === "string" ? shop.owner : null,
    phone: typeof shop.phone === "string" ? shop.phone : null,
    zone_name: typeof shop.zone_name === "string" ? shop.zone_name : null,
  };
}
