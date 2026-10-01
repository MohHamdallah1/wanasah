import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "node:path";

// Test-only in-memory HTTP fixtures. No database, worker, proxy, or business writes.
const JOB = "11111111-1111-4111-8111-111111111111";
let company = 91001;
let count = 1;
let role = "admin";
let held = false;
let corrected = false;
const requests: unknown[] = [];
const pending: Array<() => void> = [];
const row = (i: number) => ({
  row_identity: "22222222-2222-4222-8222-" + String(i + 1).padStart(12, "0"),
  row_number: i + 14, version: 3, status: "INVALID",
  values: { name: "", unit_barcode: "000" + String(i + 123), unit_price: "1.250" },
  errors: [{ code: "IMPORT_NAME_REQUIRED", field: "name" }],
  editable: true, unavailable_reason: null,
});
function fixture(): Plugin {
  return {
    name: "phase19-synthetic-http",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url || "/", "http://127.0.0.1:5187");
        if (!url.pathname.startsWith("/acceptance-api/")) return next();
        const send = (data: unknown, status = 200) => {
          res.statusCode = status;
          res.setHeader("Content-Type", "application/json");
          res.setHeader("X-Request-Id", "phase19-synthetic");
          res.end(JSON.stringify(data));
        };
        let text = "";
        for await (const chunk of req) {
          text += chunk;
          if (Buffer.byteLength(text) > 64 * 1024) return send({}, 413);
        }
        const body = text ? JSON.parse(text) : {};
        const p = url.pathname.replace("/acceptance-api", "");
        if (p === "/fixture") {
          if (req.method === "POST") {
            company = body.company ?? company;
            role = body.role ?? role;
            count = body.count ?? count;
            if (body.reset) corrected = false;
            if (body.hold !== undefined) held = body.hold;
            if (body.release) pending.splice(0).forEach((release) => release());
          }
          return send({ company, role, count, held, pending: pending.length, requests });
        }
        // Accept only synthetic credentials on this isolated origin.
        if (req.headers.authorization !== "Bearer synthetic-" + company)
          return send({ code: "UNAUTHORIZED", request_id: "phase19-synthetic" }, 401);
        requests.push({ method: req.method, path: p + url.search, company, body });
        if (p === "/inventory/access/me") {
          const permissions = role === "operator"
            ? ["catalog.manage", "catalog.publish", "pricing.manage"]
            : role === "viewer" ? ["pricing.view"] : [];
          return send({ company_id: company, driver_id: 91011, is_company_admin: role === "admin",
            location_id: null, permissions, any_permissions: permissions, location_permissions: [] });
        }
        if (p === "/simple-products/package-uoms")
          return send({ items: [{ id: 2, code: "CARTON" }] });
        if (p === "/simple-products/tracking/defaults")
          return send({ lot_control_mode: "NONE", expiry_control_mode: "OPTIONAL",
            lot_control_source: "COMPANY", expiry_control_source: "COMPANY" });
        if (p === "/simple-products") {
          const priced = role !== "restricted" && role !== "operator";
          return send({ currency_code: "JOD", pricing_visible: priced, next_cursor: null, has_more: false,
            items: [{ id: 91021, product_id: 91031, name: "منتج صناعي Synthetic", family_name: "Synthetic",
              sku: "SYN-001", units_per_package: 12, legacy_packs_per_carton: 1, base_uom_id: 1,
              base_uom_code: "PCS", package_uom_id: 2, package_uom_code: "CARTON", currency_code: "JOD",
              unit_price: priced ? "1.250" : null, package_price: priced ? "15.000" : null,
              unit_barcode: "000123", package_barcode: "000999", package_uses_base_barcode: false,
              version: 1, lot_control_mode: "NONE", expiry_control_mode: "OPTIONAL",
              lifecycle_status: "ACTIVE", operational_hold: "NONE", simple_compatible: true }] });
        }
        if (p === "/simple-products/families")
          return send({ items: [], next_cursor: null, has_more: false });
        if (p.startsWith("/simple-products/imports/" + JOB)) {
          if (company !== 91001) return send({ code: "PRODUCT_IMPORT_NOT_FOUND",
            request_id: "phase19-synthetic" }, 404);
          if (p.endsWith("/correction/rows") && req.method === "POST") {
            const finish = () => {
              corrected = true;
              send({ job_id: JOB, status: "VALIDATING", corrected_rows: body.rows.length, replayed: false });
            };
            if (held) { pending.push(finish); return; }
            return finish();
          }
          if (p.endsWith("/correction/rows")) {
            const after = Number(url.searchParams.get("after_row") || 0);
            const limit = Number(url.searchParams.get("limit") || 25);
            const items = Array.from({ length: Math.min(count, 25) }, (_, i) => row(i))
              .filter((item) => item.row_number > after).slice(0, limit);
            return send({ job_id: JOB, job_version: 7, fields: ["name", "unit_barcode", "unit_price"],
              items, next_after_row: null });
          }
          if (p === "/simple-products/imports/" + JOB)
            return send({ job_id: JOB, status: corrected ? "COMPLETED" : "COMPLETED_WITH_ERRORS",
              file_name: "synthetic-only.xlsx", total_rows: count + 2, processed_rows: count + 2,
              valid_rows: corrected ? count + 2 : 2, imported_rows: corrected ? count + 2 : 2,
              invalid_rows: corrected ? 0 : count, import_failed_rows: 0, failed_rows: corrected ? 0 : count,
              pending_rows: 0, detected_headers: [], suggested_mapping: {}, column_mapping: {},
              default_lot_control_mode: "NONE", default_expiry_control_mode: "OPTIONAL",
              error_summary: {}, errors: [] });
        }
        // Unimplemented routes fail closed; never forwarded to another server.
        return send({ code: "SYNTHETIC_ROUTE_UNIMPLEMENTED", request_id: "phase19-synthetic" }, 501);
      });
    },
  };
}
export default defineConfig({
  plugins: [react(), fixture()],
  define: { "import.meta.env.VITE_BROWSER_ACCEPTANCE": JSON.stringify("synthetic-only"),
    "import.meta.env.VITE_API_URL": JSON.stringify("http://127.0.0.1:5187/acceptance-api"),
    "import.meta.env.VITE_SENTRY_DSN": JSON.stringify("") },
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { host: "127.0.0.1", port: 5187, strictPort: true,
    headers: { "Content-Security-Policy": "connect-src 'self' ws://127.0.0.1:5187; form-action 'self'" } },
});
