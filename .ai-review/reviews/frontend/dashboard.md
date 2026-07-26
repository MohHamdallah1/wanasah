# React Dashboard Audit Report (`dashboard/src/`)

> **Phase 7 — Frontend Module Audit**
> **Scope**: `dashboard/src/App.tsx`, `dashboard/src/pages/OperationsDashboard.tsx`, `dashboard/src/pages/DispatchBoard.tsx`, `dashboard/src/pages/inventory/MainInventory.tsx`, `dashboard/src/pages/Login.tsx`, `dashboard/src/hooks/useAuthFetch.ts`
> **Cross-referenced against**: `.ai-review/04_BUSINESS_RULES.md`
> **Date**: 2026-07-24

---

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High     | 7 |
| Medium   | 10 |
| Low      | 4 |
| **Total** | **24** |

**Critical issues** center around: a hardcoded API URL in the login page that bypasses the environment-configured API base, an empty-string API fallback in the auth hook that produces broken protocol-relative URLs, and DOM-manipulation search logic in DispatchBoard that silently breaks under React reconciliation.

**High issues** include token-storage fragmentation across two localStorage keys, missing `AbortController` cleanup on multiple concurrent fetches causing memory leaks and stale-setState warnings, no type-guard before `.map()` on API responses (crash risk), aggressive 10-second recursive polling without backoff or jitter, and route guards that gate on raw localStorage presence without validating token expiry.

---

## Critical Severity

---

### 🔴 C-01: Hardcoded Backend URL in Login Page (Bypasses `VITE_API_URL`)

- **Severity**: **Critical**
- **Flaw Category**: Hardcoded Endpoint
- **Exact File & Line Number**: `dashboard/src/pages/Login.tsx`, line 43
- **Current Flawed Code**:
  ```ts
  const response = await fetch('http://127.0.0.1:5000/login', {
  ```
- **Impact Analysis**: The entire application uses `import.meta.env.VITE_API_URL` via `useAuthFetch` for every authenticated request, but the Login page has a hardcoded `http://127.0.0.1:5000/login` literal. In staging, production, or any non-localhost deployment the login silently fails with a network error. There is no fallback to the configured API base URL. A deployer changing `VITE_API_URL` sees every other page work while the login page is permanently broken.
- **Recommended Surgical Fix**:
  ```ts
  const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  // ...
  const response = await fetch(`${API}/login`, {
  ```

---

### 🔴 C-02: Empty-String API Fallback Produces Broken Protocol-Relative URLs

- **Severity**: **Critical**
- **Flaw Category**: Hardcoded Endpoint (Silent URL Corruption)
- **Exact File & Line Number**: `dashboard/src/hooks/useAuthFetch.ts`, line 6
- **Current Flawed Code**:
  ```ts
  const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  ```
- **Impact Analysis**: If `VITE_API_URL` is not set (missing `.env` file, build misconfiguration), `API` becomes `""` (empty string). Every `fetch()` call then becomes `fetch("//admin/sessions/today")` — a **protocol-relative URL** that resolves to `http://admin/sessions/today` or `https://admin/sessions/today` depending on the page's protocol. This silently produces DNS resolution failures with no clear error message. The dashboard will appear to load with infinite spinners or blank screens. This is a production-deployment time-bomb: one missing env variable takes down every page.
- **Recommended Surgical Fix**:
  ```ts
  const rawApi = (import.meta.env.VITE_API_URL || "").trim();
  if (!rawApi) {
    throw new Error(
      "VITE_API_URL is not set. The dashboard cannot function without an API base URL."
    );
  }
  const API = rawApi.replace(/\/$/, "");
  ```

> **BR Cross-Reference**: Business rule 4.3 (cash vs. debt separation) and 5.2 (settlement cash reconciliation) both depend on accurate server communication. A silently-mangled API base URL breaks every financial-reconciliation endpoint without visible trace in the UI.

---

### 🔴 C-03: DOM-Manipulation Product Search Breaks Under React Reconciliation

- **Severity**: **Critical**
- **Flaw Category**: Rendering Bug / React Anti-Pattern (Silent UI Corruption)
- **Exact File & Line Number**: `dashboard/src/pages/DispatchBoard.tsx`, lines 787–795
- **Current Flawed Code**:
  ```tsx
  onChange={(e) => {
    const val = e.target.value.toLowerCase();
    const rows = document.querySelectorAll('.product-launch-row');
    rows.forEach(row => {
      const name = row.getAttribute('data-name')?.toLowerCase() || "";
      if (name.includes(val)) {
        (row as HTMLElement).style.display = 'table-row';
      } else {
        (row as HTMLElement).style.display = 'none';
      }
    });
  }}
  ```
- **Impact Analysis**: This bypasses React's virtual DOM entirely by using `document.querySelectorAll` and mutating `HTMLElement.style.display` directly. On **any** subsequent state change in `DispatchBoard` (e.g., selecting a different zone, toggling edit mode, receiving a `setInterval` refresh of active routes), React re-renders the table rows and **resets every inline `style.display` back to `table-row`**, instantly clearing the user's search filter. The user sees products flicker back into view, then must re-type in the search box. This is a silent, non-obvious corruption of UI state — the filter appears functional but is structurally incompatible with React's rendering model.
- **Recommended Surgical Fix**:
  ```tsx
  // Add a state variable near the other useState declarations (≈line 100):
  const [productSearchQuery, setProductSearchQuery] = useState("");

  // Replace the onChange handler:
  onChange={(e) => setProductSearchQuery(e.target.value.toLowerCase())}

  // Wrap the products .map() with a filtered derivation (before line 814):
  const filteredProducts = useMemo(() => {
    if (!productSearchQuery.trim()) return products;
    const q = productSearchQuery.toLowerCase();
    return products.filter(prod => prod.name.toLowerCase().includes(q));
  }, [products, productSearchQuery]);

  // Then use filteredProducts.map(...) instead of products.map(...)
  ```

---

## High Severity

---

### 🟠 H-01: Token Storage Fragmentation — Two Competing localStorage Keys

- **Severity**: **High**
- **Flaw Category**: Token Storage Fragmentation / State Desync
- **Exact File & Line Number**: `dashboard/src/hooks/useAuthFetch.ts`, line 9
- **Current Flawed Code**:
  ```ts
  const token = localStorage.getItem("admin_token") || localStorage.getItem("token");
  ```
- **Impact Analysis**: The Login page (`Login.tsx` line 64) writes only `admin_token`. However, the auth hook also reads a legacy `token` key as a fallback. If both keys exist with different values (e.g., a stale `token` from a previous session and a fresh `admin_token` from a current login), the fallback is never reached because `admin_token` is truthy — this case is benign. However, the reverse is dangerous: if `admin_token` is cleared (e.g., by a 401 handler at line 22) but `token` still exists, the hook silently picks up the old `token` and continues making requests with a potentially expired or different-user credential. Cross-contamination of sessions between different admin accounts is possible if they share a browser.
- **Recommended Surgical Fix**:
  ```ts
  const token = localStorage.getItem("admin_token");
  if (!token) {
    localStorage.removeItem("token"); // clean legacy key
    navigate("/login");
    throw new Error("انتهت الجلسة، يرجى تسجيل الدخول مجدداً");
  }
  ```

---

### 🟠 H-02: Uncontrolled Fetch Calls Without AbortController (Memory Leak + Stale setState)

- **Severity**: **High**
- **Flaw Category**: Memory Leak / Stale Closure
- **Exact File & Line Number**: `dashboard/src/pages/DispatchBoard.tsx`, lines 173–175
- **Current Flawed Code**:
  ```ts
  authenticatedFetch("/dispatch/shops").then(data => setShops(data)).catch(err => console.error(err));
  authenticatedFetch("/dispatch/active_routes").then(data => setPendingRoutes(data)).catch(err => console.error(err));
  authenticatedFetch("/dispatch/shortages").then(data => setShortages(data)).catch(err => console.error(err));
  ```
- **Impact Analysis**: Unlike the `/dispatch/init` call (line 160) which passes `controller.signal`, these three fetch calls have **no `AbortController` signal**. If the user navigates away from the DispatchBoard tab or the component unmounts before these requests resolve, the `.then()` callbacks still fire and call `setState` on an unmounted component. React 18 batches these but still logs warnings; in React 17 or strict mode this produces "Can't perform a React state update on an unmounted component" errors. More critically, in `fetchInitialData` the `controller.abort()` on cleanup only aborts the `/dispatch/init` request — the three fire-and-forget requests continue consuming bandwidth and memory.
- **Recommended Surgical Fix**:
  ```ts
  const fetchInitialData = useCallback(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    authenticatedFetch("/dispatch/init", { signal })
      .then(data => { /* ... same ... */ })
      .catch(err => err.name !== 'AbortError' && toast.error("خطأ في الاتصال بالخادم (Init): " + err.message));

    authenticatedFetch("/dispatch/shops", { signal })
      .then(data => setShops(data))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
    authenticatedFetch("/dispatch/active_routes", { signal })
      .then(data => setPendingRoutes(data))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
    authenticatedFetch("/dispatch/shortages", { signal })
      .then(data => setShortages(data))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });

    return controller;
  }, [authenticatedFetch]);
  ```

> NOTE: The dependency array must include `authenticatedFetch`. Currently it's `[]` (line 158), which is a lint violation (exhaustive-deps).

---

### 🟠 H-03: No Type-Guard Before `.map()` — Potential Unhandled TypeError Crash

- **Severity**: **High**
- **Flaw Category**: Silent Fetch Failure / UI Crash
- **Exact File & Line Number**: `dashboard/src/pages/OperationsDashboard.tsx`, lines 114–116
- **Current Flawed Code**:
  ```ts
  const data = await authFetch("/admin/sessions/today");
  if (data && isMounted) {
    const formattedData = data.map((d: any) => {
  ```
- **Impact Analysis**: `authFetch` returns the parsed JSON body. If the backend returns a successful HTTP 200 but with a non-array JSON body (e.g., `{"status": "ok", "message": "no sessions today"}` due to a future API change or error envelope), `data` is a truthy object — the `if (data && isMounted)` guard passes — and `data.map()` throws `TypeError: data.map is not a function`. This crash is caught by the `catch` block at line 134, but the catch only runs `console.error` — **no user-facing toast, no error state in UI**. The drivers list becomes stale (last successful data), and the admin has no visible indication that data is outdated.
- **Recommended Surgical Fix**:
  ```ts
  const data = await authFetch("/admin/sessions/today");
  if (data && isMounted) {
    if (!Array.isArray(data)) {
      toast.error("تنسيق بيانات الجلسات غير متوقع من السيرفر");
      return;
    }
    const formattedData = data.map((d: any) => {
  ```

---

### 🟠 H-04: Aggressive Recursive Polling Without Backoff or Jitter

- **Severity**: **High**
- **Flaw Category**: Polling Overhead / Server Over-Polling
- **Exact File & Line Number**: `dashboard/src/pages/OperationsDashboard.tsx`, lines 144–149
- **Current Flawed Code**:
  ```ts
  const poll = async () => {
    await fetchLiveOperations(isMounted);
    if (isMounted) {
      timerId = setTimeout(poll, 10000);
    }
  };
  ```
- **Impact Analysis**: The dashboard polls `/admin/sessions/today` every 10 seconds, recursively, without interruption. With 5 admin tabs open, this produces **30 requests/minute to the same endpoint**. If the server response takes longer than 10 seconds (e.g., under load), the next poll starts **immediately** after the previous one finishes — there is no minimum interval enforcement, so under degraded server conditions, the client can stack requests. There is no exponential backoff on failure (the catch at line 134 only logs to console — the poll continues at 10s regardless), meaning a server outage causes a constant 10s hammer from every open dashboard. This violates the principle of cooperative polling and can amplify a server outage into a self-DOS.
- **Recommended Surgical Fix**:
  ```ts
  const POLL_INTERVAL = 30000; // 30 seconds, not 10
  const MAX_BACKOFF = 120000;

  const poll = async (attempt = 0) => {
    try {
      await fetchLiveOperations(isMounted);
      if (isMounted) {
        timerId = setTimeout(() => poll(0), POLL_INTERVAL);
      }
    } catch {
      if (isMounted) {
        const backoff = Math.min(POLL_INTERVAL * Math.pow(2, attempt), MAX_BACKOFF);
        timerId = setTimeout(() => poll(attempt + 1), backoff);
      }
    }
  };
  ```

> **BR Cross-Reference**: Business rule 2.2 describes the "morning load vs. mid-day handshake" invariant. The OperationsDashboard polls today's sessions to reflect real-time driver authorization status and settlement state. Polling at 10s intervals creates unnecessary server pressure when session state changes infrequently (authorization toggles, settlements happen at human speed). A 30s base interval with exponential backoff on failure is more appropriate.

---

### 🟠 H-05: Route Guards Gate on Raw localStorage Without Token Expiry Validation

- **Severity**: **High**
- **Flaw Category**: Token Storage Fragmentation / Security (No Expiry Check)
- **Exact File & Line Number**: `dashboard/src/App.tsx`, lines 17–18 and 24–25
- **Current Flawed Code**:
  ```ts
  const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
    const token = localStorage.getItem('admin_token');
    if (!token) return <Navigate to="/login" replace />;
    return children;
  };
  ```
- **Impact Analysis**: The route guard checks only for the **presence** of the `admin_token` key in localStorage. It does **not** decode the JWT, check its `exp` claim, or verify the token with the server. A token that expired 3 days ago still passes the guard, allowing the admin to navigate to protected routes. The actual API calls will fail with 401 (triggering the `useAuthFetch` redirect), but there is a race condition: the admin sees the dashboard UI render briefly (with stale/empty data) before being kicked to login. Worse, if any component renders data from localStorage (e.g., `admin_name`), the UI shows a logged-in state with no data. An admin whose account was disabled server-side retains full client-side navigation because the token is never invalidated locally.
- **Recommended Surgical Fix**:
  ```ts
  const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
    const token = localStorage.getItem('admin_token');
    if (!token) return <Navigate to="/login" replace />;

    // Basic JWT expiry check (no server verification, but catches obvious stale tokens)
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        localStorage.removeItem('admin_token');
        localStorage.removeItem('admin_name');
        localStorage.removeItem('admin_id');
        return <Navigate to="/login" replace />;
      }
    } catch {
      localStorage.removeItem('admin_token');
      return <Navigate to="/login" replace />;
    }

    return children;
  };
  ```

---

### 🟠 H-06: Login Page Stores Sensitive Session Data in localStorage (XSS Surface)

- **Severity**: **High**
- **Flaw Category**: Token Storage Fragmentation / Security
- **Exact File & Line Number**: `dashboard/src/pages/Login.tsx`, lines 64–66
- **Current Flawed Code**:
  ```ts
  localStorage.setItem('admin_token', data.token);
  localStorage.setItem('admin_name', data.driver_name);
  localStorage.setItem('admin_id', data.driver_id);
  ```
- **Impact Analysis**: The JWT token and associated user identity (`driver_name`, `driver_id`) are stored in `localStorage`, which is accessible to any JavaScript running on the same origin. A successful XSS attack (e.g., via a dependency with a compromised script, or an injected malicious package) can exfiltrate the token trivially with `localStorage.getItem('admin_token')`. There is no httpOnly cookie, no `SameSite` enforcement, and no content-security-policy header configuration evident in the Vite config. Furthermore, the `admin_name` and `admin_id` are stored as separate keys rather than decoded from the JWT on each read — if these fall out of sync with the token's actual claims (e.g., after a server-side name change), the UI displays stale identity.
- **Recommended Surgical Fix**:
  ```ts
  // Only store the token; derive name/id from the JWT payload at read time
  localStorage.setItem('admin_token', data.token);
  // Remove the admin_name and admin_id setItem calls
  ```
  And in any component that reads `admin_name` (e.g., DashboardLayout), decode from the token instead:
  ```ts
  const getAdminName = () => {
    const token = localStorage.getItem('admin_token');
    if (!token) return null;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.sub || payload.driver_name || null;
    } catch {
      return null;
    }
  };
  ```

---

### 🟠 H-07: `useAuthFetch` 401 Handler Navigates Multiple Times for Concurrent Requests

- **Severity**: **High**
- **Flaw Category**: Unhandled Re-render / Navigation Storm
- **Exact File & Line Number**: `dashboard/src/hooks/useAuthFetch.ts`, lines 21–25
- **Current Flawed Code**:
  ```ts
  if (res.status === 401) {
    localStorage.removeItem("admin_token");
    localStorage.removeItem("token");
    navigate("/login");
    throw new Error("انتهت الجلسة، يرجى تسجيل الدخول مجدداً");
  }
  ```
- **Impact Analysis**: When a token expires, **every** in-flight or subsequent `authFetch` call receives a 401. Consider `DispatchBoard.fetchInitialData()` which fires 4 concurrent requests (line 160, 173–175). All 4 get 401 → `navigate("/login")` is called 4 times in rapid succession. React Router handles this gracefully (duplicate navigations to the same path are no-ops), but the `localStorage.removeItem` calls also run 4 times, and 4 separate errors are thrown to 4 different `.catch()` handlers. This can produce 4 toast notifications, 4 console errors, and in edge cases can trigger a navigation loop if the Login page itself makes an authFetch call. There is no debounce or guard condition (e.g., checking if already navigating).
- **Recommended Surgical Fix**:
  ```ts
  let isNavigating = false; // module-level flag outside the hook

  export function useAuthFetch() {
    // ...
    return useCallback(async (path: string, opts: RequestInit = {}) => {
      // ...
      if (res.status === 401) {
        localStorage.removeItem("admin_token");
        localStorage.removeItem("token");
        if (!isNavigating) {
          isNavigating = true;
          navigate("/login");
        }
        throw new Error("انتهت الجلسة، يرجى تسجيل الدخول مجدداً");
      }
      // ...
    }, [navigate, API]);
  }
  ```

---

## Medium Severity

---

### 🟡 M-01: `SalesDetailsModal` Defined Inside Component — Re-created Every Render

- **Severity**: **Medium**
- **Flaw Category**: Unhandled Re-render (Performance Degradation)
- **Exact File & Line Number**: `dashboard/src/pages/OperationsDashboard.tsx`, lines 15–97
- **Current Flawed Code**: The entire `SalesDetailsModal` component is defined as a function **inside** the `Index` component body.
- **Impact Analysis**: On every render of `Index` (which happens every 10 seconds due to polling), a new `SalesDetailsModal` function reference is created. React treats this as a different component type on each render, causing the `AnimatePresence` to re-mount the entire modal subtree even when `isOpen` is `false`. While `isOpen: false` causes an early `return null`, the function definition itself is re-created, and any parent that receives it as a prop (it's used inline at line 289) gets a new reference on every render. This is primarily a performance issue, not a correctness bug, but in a component that re-renders every 10s × N drivers, the cumulative cost is non-trivial.
- **Recommended Surgical Fix**: Move `SalesDetailsModal` outside the `Index` component, into either the same file (above `Index`) or into `@/components/operations/SalesDetailsModal.tsx`. It receives all data via props and has no closure over `Index` state.

---

### 🟡 M-02: Silent Catch With Only `console.error` — No User Feedback on Data Fetch Failure

- **Severity**: **Medium**
- **Flaw Category**: Silent Fetch Failure
- **Exact File & Line Number**: `dashboard/src/pages/OperationsDashboard.tsx`, lines 134–136
- **Current Flawed Code**:
  ```ts
  } catch (error) {
    console.error("فشل الاتصال بالسيرفر:", error);
  }
  ```
- **Impact Analysis**: When `fetchLiveOperations` fails (network error, server 500, auth expiry), the catch block does **not** call `toast.error()` or set any error state in the UI. The driver list silently remains on the last successful data. An admin staring at the dashboard sees what appears to be live data but is actually stale — potentially hours old if the first fetch succeeded and subsequent polls all failed. This undermines the operational purpose of the dashboard (real-time fleet monitoring). A 401 in particular should redirect, not silently swallow.
- **Recommended Surgical Fix**:
  ```ts
  } catch (error: any) {
    if (error?.status === 401) return; // already handled by useAuthFetch redirect
    toast.error("تعذر تحديث بيانات الجلسات. تحقق من اتصالك بالسيرفر.");
    console.error("فشل الاتصال بالسيرفر:", error);
  }
  ```

---

### 🟡 M-03: `fetchInitialData` useCallback Missing Dependency (`authenticatedFetch`)

- **Severity**: **Medium**
- **Flaw Category**: Stale Closure / React Hooks Violation
- **Exact File & Line Number**: `dashboard/src/pages/DispatchBoard.tsx`, line 158
- **Current Flawed Code**:
  ```ts
  const fetchInitialData = useCallback(() => {
    const controller = new AbortController();
    authenticatedFetch("/dispatch/init", { signal: controller.signal })
    // ...
    return controller;
  }, []);
  ```
- **Impact Analysis**: The `useCallback` has an empty dependency array `[]` but references `authenticatedFetch` in its body. This violates the React Hooks exhaustive-deps rule. While `authenticatedFetch` is itself memoized and stable (its identity only changes if `navigate` or `API` change, which they don't in practice), this is a fragile assumption. If `useAuthFetch` is ever refactored to accept additional parameters or update its identity, `fetchInitialData` would continue using a stale reference to the old `authenticatedFetch`, potentially with an expired token or wrong API base URL. TypeScript/ESLint with `react-hooks/exhaustive-deps` would flag this.
- **Recommended Surgical Fix**:
  ```ts
  const fetchInitialData = useCallback(() => {
    // ... same body ...
  }, [authenticatedFetch]);
  ```

---

### 🟡 M-04: `Promise.all` Without Rollback — Partial Zone Scheduling Updates

- **Severity**: **Medium**
- **Flaw Category**: State Desync (Inconsistent Server State)
- **Exact File & Line Number**: `dashboard/src/pages/DispatchBoard.tsx`, lines 368–378
- **Current Flawed Code**:
  ```ts
  try {
    await Promise.all(targetIds.map(id =>
      authenticatedFetch(`/dispatch/zones/${id}`, {
        method: "PUT",
        body: JSON.stringify({ frequency: schedulingForm.frequency, visitDay: schedulingForm.visitDay, startDate: schedulingForm.startDate })
      })
    ));
    setZones(prev => sortZones(prev.map(z => targetIds.includes(z.id) ? { ...z, ...schedulingForm } : z)));
    toast.success(`تم تحديث إعدادات الجدولة لـ ${zoneNames}`);
  ```
- **Impact Analysis**: If `targetIds` contains 5 zones and the 3rd request fails (e.g., network blip, server error for that specific zone), `Promise.all` rejects immediately. Zones 1 and 2 have **already been updated** on the server, but the `setZones` optimistic update never runs — the local state remains unchanged for all 5 zones. The admin sees an error toast, assumes nothing was saved, and may retry the operation, potentially creating double-updates for zones 1–2. Meanwhile, zones 3–5 were never updated on the server. The UI is now out of sync with the server for zones 1–2. A full `fetchInitialData()` is needed to reconcile, but it's not called in the catch.
- **Recommended Surgical Fix**: Use `Promise.allSettled` to collect individual results, apply local state only for succeeded zones, and report which zones failed:
  ```ts
  const results = await Promise.allSettled(targetIds.map(id =>
    authenticatedFetch(`/dispatch/zones/${id}`, { method: "PUT", body: JSON.stringify({...}) })
  ));
  const succeededIds = targetIds.filter((_, i) => results[i].status === 'fulfilled');
  const failedIds = targetIds.filter((_, i) => results[i].status === 'rejected');
  if (succeededIds.length > 0) {
    setZones(prev => sortZones(prev.map(z => succeededIds.includes(z.id) ? { ...z, ...schedulingForm } : z)));
  }
  if (failedIds.length > 0) {
    toast.error(`فشل تحديث ${failedIds.length} مناطق. تم حفظ الباقي.`);
  } else {
    toast.success(`تم تحديث إعدادات الجدولة لـ ${zoneNames}`);
  }
  ```

---

### 🟡 M-05: Arabic Pluralization Logic Bug for Product Counts > 10

- **Severity**: **Medium**
- **Flaw Category**: UX Bug (Incorrect Localization)
- **Exact File & Line Number**: `dashboard/src/pages/inventory/MainInventory.tsx`, lines 142–146
- **Current Flawed Code**:
  ```ts
  products.length === 1 ? "منتج" :
    products.length === 2 ? "منتجان" :
      (products.length >= 3 && products.length <= 10) ? "منتجات" : "منتج"
  ```
- **Impact Analysis**: When `products.length >= 11`, the ternary falls through to the final `"منتج"` (singular). In Arabic grammar, numbers 11–99 for inanimate objects take the singular accusative form, so `"منتجًا"` (with tanween) would be correct. The bare `"منتج"` reads as the definite singular nominative, which is grammatically jarring for counts like "15 منتج". While this accidentally produces the correct root word, the intent is unclear and a future developer may "fix" it to "منتجات" (the broken plural for 11+), producing grammatically incorrect Arabic. The code also lacks a comment explaining the grammatical rule, making it appear buggy to non-Arabic-speaking maintainers.
- **Recommended Surgical Fix**:
  ```ts
  products.length === 1 ? "منتج" :
    products.length === 2 ? "منتجان" :
      (products.length >= 3 && products.length <= 10) ? "منتجات" :
        "منتج" // Arabic: 11+ takes singular accusative form for inanimate nouns
  ```

---

### 🟡 M-06: Unhandled `JSON.parse` Failure on Non-JSON API Responses

- **Severity**: **Medium**
- **Flaw Category**: Silent Fetch Failure (Crash in Hook)
- **Exact File & Line Number**: `dashboard/src/hooks/useAuthFetch.ts`, lines 28–29
- **Current Flawed Code**:
  ```ts
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  ```
- **Impact Analysis**: If the server returns a non-JSON response (e.g., an HTML error page from a reverse proxy, a plain-text 502 Bad Gateway, or a misconfigured CORS error page), `JSON.parse(text)` throws a `SyntaxError`. This error is **not caught** inside the hook — it propagates to the caller's `.catch()` handler. However, the calling code is inconsistent: `OperationsDashboard.tsx` line 134 catches it but only logs; `DispatchBoard.tsx` line 171 catches it and toasts. Worse, the `SyntaxError` message is "Unexpected token '<'" or similar, which is meaningless to an Arabic-speaking admin.
- **Recommended Surgical Fix**:
  ```ts
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      const errorInstance: any = new Error("استجابة غير صالحة من السيرفر — ربما يوجد خطأ في الشبكة.");
      errorInstance.status = res.status;
      errorInstance.data = text.substring(0, 200); // capture preview for debugging
      throw errorInstance;
    }
  }
  ```

---

### 🟡 M-07: `ledgerFetchedRef` Cache Never Invalidated Across Tab Lifecycles

- **Severity**: **Medium**
- **Flaw Category**: State Desync (Stale Data)
- **Exact File & Line Number**: `dashboard/src/pages/inventory/MainInventory.tsx`, lines 30, 88–89
- **Current Flawed Code**:
  ```ts
  const ledgerFetchedRef = useRef(false); // +++ درع حماية الـ IO لمنع التكرار (Caching) +++
  // ...
  if (!force && ledgerFetchedRef.current) return;
  // ...
  ledgerFetchedRef.current = true;
  ```
- **Impact Analysis**: The `ledgerFetchedRef` cache prevents redundant ledger fetches, which is a good optimization. However, there is **no mechanism to invalidate this cache**. If the admin performs an inbound stock operation (Tab 2), the `onSuccess` callback calls `fetchLedger(true)` (line 183), bypassing the cache — correct. But if the admin performs a stocktake (Tab 3) that modifies ledger entries, `onLockChange` does **not** call `fetchLedger` at all (line 194–197). The ledger tab will show stale data until the user manually refreshes or navigates away and back. The cache is also never reset when the component unmounts — if the admin navigates to Dispatch and back to Inventory, the `ledgerFetchedRef` is still `true` (React preserves refs across remounts because the component key doesn't change).
- **Recommended Surgical Fix**: Reset the ref in the cleanup of the mount effect:
  ```ts
  useEffect(() => {
    ledgerFetchedRef.current = false;
    fetchStatus();
    fetchStock();
    fetchAlerts();
    return () => { ledgerFetchedRef.current = false; };
  }, []);
  ```
  And add `fetchLedger(true)` to the stocktake `onLockChange` callback (line 194):
  ```ts
  onLockChange={async (locked) => {
    setIsAuditLocked(locked);
    await Promise.all([fetchStock(), fetchAlerts(), fetchLedger(true)]);
  }}
  ```

---

### 🟡 M-08: `fetch` Has No Timeout — Hanging Requests Block UI Indefinitely

- **Severity**: **Medium**
- **Flaw Category**: Silent Fetch Failure (Indefinite Loading)
- **Exact File & Line Number**: `dashboard/src/hooks/useAuthFetch.ts`, line 12
- **Current Flawed Code**:
  ```ts
  const res = await fetch(`${API}${cleanPath}`, {
  ```
- **Impact Analysis**: The native `fetch` API has **no built-in timeout**. If the server accepts the TCP connection but never responds (e.g., a stuck thread, a deadlocked database query, a network partition that doesn't send RST), the `fetch` promise never resolves or rejects. The UI shows an infinite loading spinner. All calling code that uses `await authFetch(...)` blocks indefinitely, and since `authFetch` is the single communication channel, the entire dashboard hangs. In `OperationsDashboard`, the recursive polling at line 149 uses `await fetchLiveOperations(isMounted)` — if one poll hangs, the next poll is never scheduled, and the dashboard freezes on stale data. The admin must manually refresh the page.
- **Recommended Surgical Fix**:
  ```ts
  const TIMEOUT_MS = 15_000; // 15 seconds
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${API}${cleanPath}`, {
      ...opts,
      signal: opts.signal
        ? combineSignals(opts.signal, controller.signal)
        : controller.signal,
      headers: { /* ... same ... */ },
    });
    clearTimeout(timeoutId);
    // ... rest of logic ...
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError' && !opts.signal?.aborted) {
      throw new Error("انتهت مهلة الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.");
    }
    throw err;
  }
  ```
  (Implement a simple `combineSignals` helper or use `AbortSignal.any()` if targeting modern browsers.)

> **BR Cross-Reference**: Business rule 2.2 (mid-day handshake) and rule 6.1 (write-path priority) both depend on reliable, timely server communication. A hanging request during a settlement confirmation (`handleConfirmSettlement` at line 234) could leave the admin uncertain whether the settlement was persisted, potentially leading to a duplicate attempt.

---

### 🟡 M-09: `setInterval` in DispatchBoard Does Not Refresh Zones or Shops

- **Severity**: **Medium**
- **Flaw Category**: State Desync (Stale Data)
- **Exact File & Line Number**: `dashboard/src/pages/DispatchBoard.tsx`, lines 183–186
- **Current Flawed Code**:
  ```ts
  const interval = setInterval(() => {
    authenticatedFetch("/dispatch/active_routes").then(data => setPendingRoutes(data)).catch(() => { });
    authenticatedFetch("/dispatch/shortages").then(data => setShortages(data)).catch(() => { });
  }, 60000);
  ```
- **Impact Analysis**: The auto-refresh interval updates `pendingRoutes` and `shortages` every 60 seconds, but **does not refresh `zones`, `shops`, or `drivers`**. If another admin adds a new shop, creates a zone, or adds a driver, the current admin's DispatchBoard will not see these changes until they manually trigger a full refresh (e.g., by navigating tabs). This creates a multi-admin split-brain: Admin A assigns a driver to a zone that Admin B created 5 minutes ago, but Admin A's dispatch form still shows the old driver list, resulting in a failed dispatch with a confusing error. The 60-second interval gives a false sense of "real-time" when only 2 of 5 data domains are actually refreshed.
- **Recommended Surgical Fix**: Either refresh all data domains or remove the selective auto-refresh and replace with a visible "Last updated: X seconds ago — Refresh" button that triggers `fetchInitialData()`. The selective partial refresh is misleading.
  ```ts
  const interval = setInterval(() => {
    fetchInitialData(); // full refresh
  }, 120000); // 2 minutes; with a "Refresh" button for on-demand
  ```

---

### 🟡 M-10: `handleConfirmSettlement` Error Handling — Undefined `.message` on TypeError

- **Severity**: **Medium**
- **Flaw Category**: Unhandled API Error (Misleading Toast)
- **Exact File & Line Number**: `dashboard/src/pages/OperationsDashboard.tsx`, line 247
- **Current Flawed Code**:
  ```ts
  } catch (error: any) {
    toast.error(error.message || "حدث خطأ أثناء التسوية");
  }
  ```
- **Impact Analysis**: If the fetch itself fails (network disconnected, DNS failure, CORS error), `error` is a `TypeError` (e.g., "Failed to fetch"). `TypeError` instances have a `message` property, so this case works. However, if `authFetch` throws a custom error (line 33 of `useAuthFetch.ts`) that was constructed with `new Error(...)`, the `.message` is the server's message — fine. The dangerous case: if `error` is thrown from somewhere else (e.g., a bug in the authFetch hook where a non-Error object is thrown), `error.message` is `undefined`, and the toast shows the fallback string. The admin sees "حدث خطأ أثناء التسوية" with no actionable detail. The same pattern exists on line 265 (`handleUndoEndWork`), line 248 (`handleConfirmSettlement` success path has `error.message || "حدث خطأ أثناء التسوية"`), and throughout DispatchBoard (e.g., line 171 `err.message`, line 250 `err.message`).
- **Recommended Surgical Fix**:
  ```ts
  } catch (error: any) {
    const message = error?.message || (typeof error === 'string' ? error : "حدث خطأ غير معروف أثناء التسوية");
    toast.error(message);
  }
  ```

---

## Low Severity

---

### 🟢 L-01: Clock `setInterval` in Login Page — Unnecessary 1-Second Render Cadence

- **Severity**: **Low**
- **Flaw Category**: Unhandled Re-render (Minor Performance)
- **Exact File & Line Number**: `dashboard/src/pages/Login.tsx`, lines 13–17
- **Current Flawed Code**:
  ```ts
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);
  ```
- **Impact Analysis**: The clock updates every second, triggering a full component re-render (and re-render of all children) on each tick. On the Login page this is negligible since the form is simple. However, the `mousemove` handler at line 23 also fires on every mouse pixel movement, creating a constantly-repainting page. On low-power devices (e.g., an old tablet used as a wall-mounted dashboard display), the combined 1s `setInterval` + mousemove listener can cause noticeable battery drain and heat. Not critical — the clock is a cosmetic element — but worth noting as an easily fixable inefficiency.
- **Recommended Surgical Fix**: The clock is non-essential; reduce the update to every 10s or remove the seconds display. Or encapsulate it in a separate component with `React.memo` to prevent parent re-renders.

---

### 🟢 L-02: `mousemove` Listener Re-registered on Every Render of Login Page

- **Severity**: **Low**
- **Flaw Category**: Unhandled Re-render (Event Listener Churn)
- **Exact File & Line Number**: `dashboard/src/pages/Login.tsx`, lines 21–30
- **Current Flawed Code**:
  ```ts
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const spotlight = document.getElementById('mouse-spotlight-login');
      if (spotlight) {
        spotlight.style.background = `radial-gradient(...)`;
      }
    };
    document.addEventListener('mousemove', handleMouseMove);
    return () => document.removeEventListener('mousemove', handleMouseMove);
  }, []);
  ```
- **Impact Analysis**: The effect has an empty dependency array `[]`, so the listener is registered once on mount and removed on unmount — this is actually correct. However, `handleMouseMove` performs a DOM query (`document.getElementById`) on **every single mouse movement** (hundreds of times per second during active mouse use). The `spotlight` element's ID is not cached, so `getElementById` is called on every pixel. This is a minor performance drain. The gradient string is also reconstructed on every call. Not a bug, but a performance anti-pattern.
- **Recommended Surgical Fix**: Cache the element reference in a ref:
  ```ts
  const spotlightRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    spotlightRef.current = document.getElementById('mouse-spotlight-login');
  }, []);
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (spotlightRef.current) {
        spotlightRef.current.style.background = `radial-gradient(...)`;
      }
    };
    document.addEventListener('mousemove', handleMouseMove);
    return () => document.removeEventListener('mousemove', handleMouseMove);
  }, []);
  ```

---

### 🟢 L-03: `QueryClient` Instantiated at Module Scope Without Default Error Handling

- **Severity**: **Low**
- **Flaw Category**: Unhandled API Error (No Global Query Error Handler)
- **Exact File & Line Number**: `dashboard/src/App.tsx`, line 13
- **Current Flawed Code**:
  ```ts
  const queryClient = new QueryClient();
  ```
- **Impact Analysis**: The `QueryClient` is created without any `defaultOptions`. In particular, there is no global `onError` handler for queries/mutations. If any component uses `@tanstack/react-query` hooks (the project imports `QueryClientProvider` and has the package in dependencies), failed queries will retry 3 times by default with exponential backoff and then silently sit in an error state. Without a global error handler, each query consumer must handle errors individually, which is error-prone. The current codebase appears to use manual `useAuthFetch` + `useState` patterns rather than react-query hooks, so this is dormant but present.
- **Recommended Surgical Fix**:
  ```ts
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        onError: (error: any) => {
          toast.error(error?.message || "حدث خطأ غير متوقع");
        },
      },
    },
  });
  ```

---

### 🟢 L-04: DispatchBoard Active Tab State Stored in `localStorage` With No Type Safety

- **Severity**: **Low**
- **Flaw Category**: State Storage (Minor)
- **Exact File & Line Number**: `dashboard/src/pages/DispatchBoard.tsx`, lines 57–58, 69
- **Current Flawed Code**:
  ```ts
  const [activeTab, setActiveTab] = useState<string>(() => localStorage.getItem("activeTab") || "routes");
  // ...
  useEffect(() => { localStorage.setItem("activeTab", activeTab); }, [activeTab]);
  ```
- **Impact Analysis**: The tab state is persisted to `localStorage` under the generic key `"activeTab"`. If another part of the application uses the same key (e.g., `MainInventory` or a future module), the values will collide. Currently `MainInventory` uses React state only for its tab (line 26), so there's no immediate collision, but the key name `"activeTab"` is ambiguous. Additionally, the stored value is a string, and the initializer annotates `useState<string>`, but line 56's comment acknowledges the `TabId` type doesn't include `"launch"` — this is a deliberate type bypass. If a corrupted value is stored (e.g., manual localStorage manipulation), the UI will render none of the tab bodies, showing an empty content area.
- **Recommended Surgical Fix**: Use a namespaced key:
  ```ts
  localStorage.getItem("wanasah_dispatch_active_tab") || "routes"
  ```
  And add a runtime guard:
  ```ts
  const validTabs = ["routes", "launch", "zones"];
  const stored = localStorage.getItem("wanasah_dispatch_active_tab");
  const initialTab = stored && validTabs.includes(stored) ? stored : "routes";
  ```

---

## Business Rules Cross-Reference Summary

| Business Rule (Section) | Dashboard Compliance | Issue(s) |
|---|---|---|
| 1.3 Negative-stock prevention | ✅ Relies on backend validation | — |
| 1.4 Warehouse audit lock | ✅ `MainInventory` fetches and respects lock status (line 76) | M-07: Ledger cache not invalidated on stocktake |
| 2.2 Morning load vs. mid-day handshake | ✅ DispatchBoard correctly calls `/dispatch/route` with inventory payload | M-09: Stale zone/driver data in refresh interval |
| 2.3 Session lifecycle | ✅ Dashboard lists sessions; toggle authorization calls dedicated endpoint | H-04: Aggressive polling on session endpoint |
| 2.4 Sell authorization ("green light") | ✅ Implemented in `handleToggleAuth` (OpDashboard:207) with optimistic UI | — |
| 5.2 Cash reconciliation | ✅ Settlement modal passes `actual_cash` to settle endpoint | M-10: Poor error messages on settlement failure |
| 5.3 Inventory reconciliation | ✅ Settlement modal passes `inventory_jard` | — |
| 5.4 Stock disposition at close | ✅ Backend-level concern; dashboard does not implement disposition logic | — |
| 6.1 Offline write-path priority | ❌ Not applicable (dashboard is online-only) | — |

---

## Additional Observations (Not Classified as Bugs)

1. **DispatchBoard Component Size**: At 1211 lines, `DispatchBoard.tsx` is the largest component in the codebase. It manages ~40 `useState` variables and 7 modal states. This violates the Single Responsibility Principle and makes testing/debugging difficult. A future refactor should extract tab contents into separate components and consolidate state into `useReducer`.

2. **No React Router Lazy Loading**: All page components are imported statically at the top of `App.tsx` (lines 7–10). The entire dashboard bundle (including the heavy DispatchBoard with all its modal sub-components) is downloaded on first load. React's `lazy()` + `Suspense` could reduce the initial bundle by ~60%.

3. **`vite.config.ts` Environment Variables**: The `useAuthFetch` hook depends on `import.meta.env.VITE_API_URL`. There is no `.env.example` file in the dashboard directory to document this required variable.

4. **No Error Boundary**: None of the page components are wrapped in a React Error Boundary. An unhandled render-time exception in any dashboard page crashes the entire SPA to a white screen.

5. **`dashboard/src/data/operations-data.ts`** (`getFleetStats`): This file is imported but was not in the audit scope. The `stats` object (OpDashboard line 161) drives the PulseBar component. If `getFleetStats` has a division-by-zero or malformed input, it could crash the dashboard.

---

*End of Report — 24 issues found (3 Critical, 7 High, 10 Medium, 4 Low)*