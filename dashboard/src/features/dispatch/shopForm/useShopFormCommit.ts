import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { toast } from "sonner";
import { apiErrorCode, apiErrorMessage, apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import {
  completeDurableOperation, getOrCreateDurableCommand, readDurableCommand,
} from "@/lib/durableOperations";
import {
  clearShopAttemptCanonicalId, clearShopAttemptServerReference,
  createPayload, createdShopVerified, financeReadback,
  findCreatedShopAfterUnknownWrite, isShopCreateAttempt, isShopEditAttempt,
  metadataPayload, metadataVerified, shopEditAttemptScope,
  readShopAttemptCanonicalId, readShopAttemptServerReference,
  saveShopAttemptCanonicalId, saveShopAttemptServerReference, shopCreateAttemptScope,
  withExclusiveShopCreateLock,
  ShopFormInputError, type ShopCreateAttempt, type ShopEditAttempt,
  type ShopCreatePayload, type ShopFormState,
  type ShopFinanceReadback,
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
  durableId?: string;
  durableScope?: string;
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
  onRestoreForm?: (draft: ShopFormState) => void;
}

/** One Shop form commit boundary, never a finance-adjustment workflow. */
export function useShopFormCommit({
  open, editId, form, language, session, canViewFinances, busy, setBusy,
  fetch, onVerified, onClose, onRestoreForm,
}: Args) {
  const mounted = useRef(true);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const [finance, setFinance] = useState<ShopFinanceReadback | null>(null);
  const [financeLoading, setFinanceLoading] = useState(false);
  const [duplicate, setDuplicate] = useState<DuplicateShopWarning | null>(null);
  const [pending, setPending] = useState<PendingVerification | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [recoveryUnreadable, setRecoveryUnreadable] = useState(false);
  const [serverReference, setServerReference] = useState<string | null>(null);
  const restoreFormRef = useRef(onRestoreForm);
  restoreFormRef.current = onRestoreForm;
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
    setRecoveryUnreadable(false);
    setServerReference(null);
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


  // Restore before allowing another CREATE. The durable record remains after
  // canonical logout, page reload, or safe exit; only the same identity sees it.
  useEffect(() => {
    if (!open) { setRestoring(false); return; }
    const token = generation.current;
    let active = true;
    setRestoring(true);
    const scope = editId === null ? shopCreateAttemptScope() : shopEditAttemptScope(editId);
    if (!scope) {
      setRecoveryUnreadable(true);
      setRestoring(false);
      return;
    }
    void readDurableCommand<ShopCreateAttempt | ShopEditAttempt>(scope).then(record => {
      if (!active || !current(token) || !record) return;
      if (editId !== null) {
        if (!isShopEditAttempt(record.payload, editId)) {
          setRecoveryUnreadable(true);
          return;
        }
        setPending({
          id: editId, mode: "edit", payload: record.payload.submitted,
          durableId: record.requestId, durableScope: scope,
        });
        setServerReference(readShopAttemptServerReference(scope, record.requestId));
        restoreFormRef.current?.(record.payload.draft);
        setFeedback(shopFormText(language, "editRecovered"));
        return;
      }
      const createAttempt = record.payload;
      if (!isShopCreateAttempt(createAttempt)) {
        setRecoveryUnreadable(true);
        return;
      }
      const serverShopId = readShopAttemptCanonicalId(scope, record.requestId);
      setPending(previous =>
        previous?.mode === "create" && previous.durableId === record.requestId &&
        previous.id ? previous : {
          id: serverShopId, mode: "create", payload: createAttempt.submitted,
          baselineIds: createAttempt.baselineIds,
          durableId: record.requestId, durableScope: scope,
        },
      );
      setServerReference(readShopAttemptServerReference(scope, record.requestId));
      restoreFormRef.current?.(createAttempt.draft);
      setFeedback(shopFormText(language, "createRecovered"));
    }).catch(() => {
      if (active && current(token)) setRecoveryUnreadable(true);
    }).finally(() => {
      if (active && current(token)) setRestoring(false);
    });
    return () => { active = false; };
  }, [open, editId, session, current, language]);

  const clearAttempt = useCallback((verification: PendingVerification): void => {
    if (!verification.durableScope || !verification.durableId) return;
    completeDurableOperation(verification.durableScope, verification.durableId);
    clearShopAttemptServerReference(verification.durableScope);
    clearShopAttemptCanonicalId(verification.durableScope);
  }, []);

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
      clearAttempt(verification);
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
  }, [fetch, current, language, onVerified, onClose, clearAttempt]);

  const verify = useCallback(async (): Promise<boolean> => {
    if (!pending || inFlight.current || busy || restoring || recoveryUnreadable) return false;
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
  }, [pending, busy, restoring, recoveryUnreadable, setBusy, finish, session]);

  const submit = useCallback(async (forcePayload?: ShopCreatePayload): Promise<boolean> => {
    if (busy || inFlight.current || pending || !open || restoring || recoveryUnreadable) return false;
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
    let durableId: string | undefined;
    let durableScope: string | undefined;
    let mutationStarted = false;
    const attemptScope = editId ? shopEditAttemptScope(editId) : shopCreateAttemptScope();
    try {
      const performWrite = async (): Promise<boolean> => {
      if (!editId) {
        // Revalidate pending storage BEFORE network or POST: re-login and
        // concurrent tabs may have created a pending operation already.
        const scope = attemptScope;
        if (!scope) {
          setRecoveryUnreadable(true);
          return false; // never POST without a strict company/principal scope
        }
        const previous = await readDurableCommand<ShopCreateAttempt>(scope);
        if (!current(token)) return false;
        if (previous) {
          if (!isShopCreateAttempt(previous.payload)) {
            setRecoveryUnreadable(true);
            return false;
          }
          setPending({
            id: readShopAttemptCanonicalId(scope, previous.requestId),
            mode: "create", payload: previous.payload.submitted,
            baselineIds: previous.payload.baselineIds,
            durableScope: scope, durableId: previous.requestId,
          });
          setServerReference(readShopAttemptServerReference(scope, previous.requestId));
          restoreFormRef.current?.(previous.payload.draft);
          setFeedback(shopFormText(language, "createRecovered"));
          return false; // no duplicate POST even if the clicked draft is different
        }
        // If offline here, NO mutation has been attempted, so a normal retry
        // remains safe and no unknown durable record is installed.
        const before = await fetch("/dispatch/shops", { cache: "no-store" });
        if (!current(token)) return false;
        if (!Array.isArray(before) || !before.every(row =>
          row && typeof row === "object" && /^\d+$/.test(String((row as { id?: unknown }).id ?? "")))) {
          throw new Error("SHOP_FORM_PRECREATE_SNAPSHOT_INVALID");
        }
        baselineIds = before.map(row => String((row as { id: unknown }).id));
        // Write the full immutable attempt BEFORE calling POST. Failure to
        // persist is a definitive unsent condition, never a best-effort send.
        const attempt: ShopCreateAttempt = {
          kind: "SHOP_CREATE_UNCERTAIN_V1",
          clientAttemptNonce: crypto.randomUUID(), // mutex, not a server receipt
          submitted: create!, draft: { ...form }, baselineIds,
        };
        const command = await getOrCreateDurableCommand(scope, attempt);
        if (!current(token)) return false;
        durableId = command.requestId;
        durableScope = scope;
      } else {
        // Persist original metadata draft BEFORE PUT as well: offline PUT
        // and changed server rows are both ambiguous without operation proof.
        const scope = attemptScope;
        if (!scope) {
          setRecoveryUnreadable(true);
          return false;
        }
        const previous = await readDurableCommand<ShopEditAttempt>(scope);
        if (!current(token)) return false;
        if (previous) {
          if (!isShopEditAttempt(previous.payload, editId)) {
            setRecoveryUnreadable(true);
            return false;
          }
          setPending({
            id: editId, mode: "edit", payload: previous.payload.submitted,
            durableScope: scope, durableId: previous.requestId,
          });
          setServerReference(readShopAttemptServerReference(scope, previous.requestId));
          restoreFormRef.current?.(previous.payload.draft);
          setFeedback(shopFormText(language, "editRecovered"));
          return false; // Do not replay an edit with an unverified outcome
        }
        const attempt: ShopEditAttempt = {
          kind: "SHOP_METADATA_EDIT_UNCERTAIN_V1",
          clientAttemptNonce: crypto.randomUUID(),
          shopId: editId, submitted: metadata, draft: { ...form },
        };
        const command = await getOrCreateDurableCommand(scope, attempt);
        if (!current(token)) return false;
        durableId = command.requestId;
        durableScope = scope;
      }
      mutationStarted = true;
      const response = await fetch(editId ? `/dispatch/shops/${editId}` : "/dispatch/shops", {
        method: editId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      if (!current(token)) return false;
      const id = editId || parseCreatedId(response);
      if (!editId && durableScope && durableId) {
        // Only a real POST-201 shop_id is stored as an authoritative receipt.
        // A similar Shop row, timeout or response-less POST MUST NOT create one.
        saveShopAttemptCanonicalId(durableScope, durableId, id);
      }
      const verification: PendingVerification = {
        id, mode, payload, baselineIds, durableId, durableScope,
      };
      setPending(verification); // lock repeat mutation until authorized GET verifies
      return await finish(token, verification);
      };
      if (!editId) {
        if (!attemptScope) {
          setRecoveryUnreadable(true);
          return false;
        }
        if (typeof navigator === "undefined" || !navigator.locks?.request) {
          setFeedback(shopFormText(language, "createLockUnavailable"));
          return false; // never issue POST without cross-tab exclusion
        }
        const locked = await withExclusiveShopCreateLock(attemptScope, performWrite);
        if (!locked.acquired) {
          if (current(token)) setFeedback(shopFormText(language, "createOtherTab"));
          return false;
        }
        return locked.result ?? false;
      }
      return await performWrite();
    } catch (error) {
      if (!current(token)) return false;
      const status = apiErrorStatus(error);
      const code = apiErrorCode(error);
      const reference = apiErrorRequestId(error);
      if (durableId && durableScope) {
        saveShopAttemptServerReference(durableScope, durableId, reference);
        setServerReference(readShopAttemptServerReference(durableScope, durableId));
      }
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
          clearAttempt({ id: null, mode, payload, durableScope, durableId });
          setDuplicate({ shopData: existing, payload: create! });
          return false;
        }
      }
      if (status !== null && [400, 401, 403, 404, 409, 422].includes(status)) {
        // Definitive server rejection: no write committed, release its scope.
        clearAttempt({ id: editId, mode, payload, durableScope, durableId });
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
        setPending({ id: editId, mode, payload, baselineIds, durableScope, durableId });
      }
      return false;
    } finally {
      inFlight.current = false;
      // The verified success closes the modal and invalidates generation.
      // inFlight serializes this hook, so release its shared busy flag even
      // after this form closes; never update an unmounted or logged-out session.
      if (mounted.current && isDashboardSessionCurrent(session)) setBusy(false);
    }
  }, [busy, pending, open, restoring, recoveryUnreadable, form, editId, fetch, current, language,
    setBusy, finish, refreshAfterConflict, session, clearAttempt]);

  /** Explicit exit leaves either unresolved CREATE or EDIT in scoped durable
   * storage. Returning to that Shop rehydrates the frozen metadata draft.
   * A new PUT/POST never happens merely because the modal was reopened.
   */
  const leaveUncertain = useCallback((): void => {
    if (!open || busy || inFlight.current || !pending ||
      !pending.durableId || !pending.durableScope ||
      !isDashboardSessionCurrent(session)) return;
    onClose(); // preserve immutable operation and draft
  }, [open, busy, pending, session, onClose]);

  const save = useCallback(() => submit(), [submit]);
  const confirmDuplicate = useCallback(async (): Promise<boolean> => {
    if (!duplicate) return false;
    setDuplicate(null);
    return submit({ ...duplicate.payload, force_save: true });
  }, [duplicate, submit]);
  return {
    save, verify, confirmDuplicate, duplicate, clearDuplicate: () => setDuplicate(null),
    finance, financeLoading, feedback, needsVerification: pending !== null,
    restoring, recoveryUnreadable, leaveUncertain,
    needsManualReconciliation: Boolean(pending?.mode === "create" && pending.durableId),
    needsEditReview: Boolean(pending?.mode === "edit" && pending.durableId),
    localTrackingId: pending?.durableId ?? null,
    serverReference,
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
