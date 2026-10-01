"""Browser → actual FastAPI/PG16/Worker acceptance on the owned P19 cluster.

This is a small, synthetic correction journey, not a 50k rerun, real mobile
touch device, real screen reader, customer data or production deploy.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
import psycopg
import websocket
from sqlalchemy.engine import make_url

if (os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1" or
    os.environ.get("WANASAH_P19_REAL_BROWSER_CONFIRM") != "DISPOSABLE_PG16_ONLY"):
    raise RuntimeError("Real browser acceptance requires disposable-only opt-in.")
for key in ("DATABASE_URL", "DATABASE_URL_MIGRATION"):
    url = make_url(os.environ.get(key, ""))
    if (url.host, url.database, int(url.port or 0)) != (
        "127.0.0.1", "p19_http_synthetic", 55446
    ):
        raise RuntimeError("Real browser acceptance refuses non-disposable database.")

from api.auth import create_access_token
from domains.simple_products.imports.domain.localization import EN_IMPORT_LOCALE
from scripts import product_import_phase19_http_isolated_child as shared
from scripts.product_import_business_integrity_gate import _assert_business_evidence
from scripts.run_product_import_phase19_live_load import build_source

DASHBOARD = Path(__file__).resolve().parents[2] / "dashboard"
FRONTEND = "http://127.0.0.1:5188"
DEBUG = "http://127.0.0.1:19226"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def ensure_free(port: int) -> None:
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("Owned real-browser acceptance port is already occupied.")


def spawn(label: str, args: list[str], cwd: Path, env: dict[str, str]):
    log = (shared.LOG_DIR / (label + ".log")).open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT)
    except BaseException:
        log.close()
        raise
    proc.p19_label = label
    return proc, log


def wait_ready(address: str, processes, seconds: float = 40):
    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        if any(proc.poll() is not None for proc, _ in processes):
            raise RuntimeError("Owned browser/Vite/Worker exited before readiness.")
        try:
            with httpx.Client(timeout=1) as client:
                if client.get(address).status_code == 200:
                    return
        except httpx.RequestError:
            pass
        time.sleep(.2)
    raise RuntimeError("Owned browser test service never became ready.")


class CDP:
    def __init__(self):
        with httpx.Client(timeout=2) as client:
            pages = client.get(DEBUG + "/json").json()
        page = next((row for row in pages if row.get("type") == "page"), None)
        if not page:
            raise RuntimeError("Dedicated Edge has no automation page.")
        self.ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=12,
            origin=FRONTEND,
        )
        self.id = 0
        self.call("Page.enable")
        self.call("Runtime.enable")

    def call(self, method: str, params: dict | None = None):
        self.id += 1
        request_id = self.id
        self.ws.send(json.dumps({"id": request_id, "method": method,
                                 "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError("Edge CDP command failed: " + method)
            return message.get("result", {})

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError("Real browser failed a script assertion.")
        return result.get("result", {}).get("value")

    def until(self, expression: str, label: str, seconds: float = 35):
        limit = time.monotonic() + seconds
        while time.monotonic() < limit:
            if self.evaluate(expression):
                return
            time.sleep(.2)
        raise RuntimeError("Real browser assertion not reached: " + label)

    def key(self, key: str, code: str, windows_code: int):
        self.call("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key, "code": code,
            "windowsVirtualKeyCode": windows_code,
        })
        self.call("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key, "code": code,
            "windowsVirtualKeyCode": windows_code,
        })

    def close(self):
        self.ws.close()


def six_row_fixture() -> bytes:
    source, _mapping, _prefix = build_source(
        6, "P19BROWSER" + uuid4().hex[:12]
    )
    rows = list(csv.reader(io.StringIO(source.decode("utf-8-sig"))))
    name = EN_IMPORT_LOCALE.template.headers["name"]
    name_position = rows[0].index(name)
    rows[1][name_position] = ""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def browser_journey(token: str, job: str, processes) -> dict:
    ensure_free(5188)
    ensure_free(19226)
    if not EDGE.is_file():
        raise RuntimeError("Edge executable missing: cannot claim real-browser acceptance.")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node missing for existing Vite.")
    env = os.environ.copy()
    env["WANASAH_P19_REAL_BROWSER_CONFIRM"] = "DISPOSABLE_PG16_ONLY"
    vite = spawn("browser-vite", [
        node, str(DASHBOARD / "node_modules" / "vite" / "bin" / "vite.js"),
        "--config", "vite.phase19-real-browser.config.ts"
    ], DASHBOARD, env)
    processes.append(vite)
    wait_ready(FRONTEND + "/phase19-real-browser.html", processes)

    profile = Path(tempfile.mkdtemp(prefix="wanasah_p19_real_edge_"))
    edge = None
    cdp = None
    try:
        edge = spawn("browser-edge", [str(EDGE),
            "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=19226",
            "--remote-allow-origins=" + FRONTEND,
            "--user-data-dir=" + str(profile), "about:blank"
        ], profile, env)
        processes.append(edge)
        wait_ready(DEBUG + "/json", processes)
        cdp = CDP()
        cdp.call("Page.navigate", {"url": FRONTEND + "/__p19_bootstrap__"})
        cdp.until("location.origin === " + json.dumps(FRONTEND),
                  "browser reaches isolated origin")
        # No bearer in a URL, fixture, committed asset, report or console.
        cdp.evaluate("(() => {localStorage.setItem('admin_token', " +
                     json.dumps(token) + ");" +
                     "localStorage.setItem('company_id','2');" +
                     "localStorage.setItem('driver_id','1');" +
                     "localStorage.setItem('wanasah.language','ar');" +
                     "sessionStorage.setItem('wanasah:product-import:v1:2:1'," +
                     json.dumps(job) + ");return true;})()")
        cdp.call("Page.navigate", {"url": FRONTEND + "/phase19-real-browser.html"})
        cdp.until("Boolean(document.querySelector('.products-a11y-scope'))",
                  "real ProductsPage rendered")
        cdp.until("Boolean([...document.querySelectorAll('button[title]')]" +
                  ".find(x => /استيراد|import/i.test(x.title)))",
                  "real authorized import action visible")
        cdp.until("document.documentElement.lang==='ar' && " +
                  "document.documentElement.dir==='rtl'", "Arabic RTL")

        # Use an actual browser key event for the real Radix import menu.
        focused = cdp.evaluate("(() => { const b=[...document.querySelectorAll(" +
            "'button[title]')].find(x=>/استيراد|import/i.test(x.title));" +
            "if(!b)return false; b.focus(); return document.activeElement===b; })()")
        if not focused:
            raise RuntimeError("Import action is not keyboard-focusable.")
        cdp.key("ArrowDown", "ArrowDown", 40)
        cdp.until("Boolean(document.querySelector('[role=menuitem]'))",
                  "real import menu opened via ArrowDown")
        cdp.evaluate("(() => { const x=document.querySelector('[role=menuitem]');" +
                     "x.focus();return true; })()")
        cdp.key("Enter", "Enter", 13)
        cdp.until("Boolean(document.querySelector('[role=dialog]'))",
                  "original import dialog opened via keyboard")
        cdp.until("Boolean(document.querySelector('[role=dialog] section[aria-label] li input[aria-invalid=true]'))",
                  "actual PostgreSQL rejected row rendered via live HTTP")
        if not cdp.evaluate("document.querySelector('[role=dialog]')" +
                            ".contains(document.activeElement)"):
            raise RuntimeError("Focus escaped actual import modal.")
        before = cdp.evaluate("(() => { const d=document.querySelector('[role=dialog]');" +
            "const input=d.querySelector('section[aria-label] li input[aria-invalid=true]');" +
            "return {rowCount:d.querySelectorAll('section[aria-label] li').length," +
            "badValue:input.value,dir:d.getAttribute('dir')," +
            "issue:!!input.getAttribute('aria-describedby')};})()")
        if before["rowCount"] != 1 or before["badValue"] != "" or not before["issue"]:
            raise RuntimeError("Real row, field error or accessible reason mismatch.")

        # React-controlled input receives a normal DOM input event. The PATCH
        # is generated only by the existing Product Import UI/hook.
        cdp.evaluate("(() => {const input=document.querySelector(" +
            "'[role=dialog] section[aria-label] li input[aria-invalid=true]');" +
            "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')" +
            ".set.call(input,'P19 Browser Corrected');" +
            "input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()")
        cdp.until("Boolean([...document.querySelectorAll(" +
            "'[role=dialog] section[aria-label] button')]" +
            ".some(b=>!b.disabled && /حفظ|save/i.test(b.textContent)))",
            "real correction save enabled")
        clicked = cdp.evaluate("(() => { const buttons=[...document.querySelectorAll(" +
            "'[role=dialog] section[aria-label] button')];" +
            "const save=buttons.find(b=>!b.disabled && /حفظ|save/i.test(b.textContent));" +
            "if(!save)return false;save.click();return true;})()")
        if not clicked:
            raise RuntimeError("Real inline correction did not submit.")
        cdp.until("!document.querySelector('[role=dialog] section[aria-label] li input')",
                  "live UI displayed correction completion", seconds=40)

        # Language change is a React change event on the original page.
        cdp.evaluate("(() => {const x=document.getElementById('p19-real-language');" +
            "x.value='en';x.dispatchEvent(new Event('change',{bubbles:true}));" +
            "return true;})()")
        cdp.until("document.documentElement.lang==='en' && " +
                  "document.documentElement.dir==='ltr'", "English LTR")
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": 390, "height": 844, "deviceScaleFactor": 1,
            "mobile": True,
        })
        cdp.until("innerWidth===390 && document.documentElement.dir==='ltr'",
                  "390px browser viewport")
        measure = cdp.evaluate("(() => ({width:innerWidth," +
            "overflow:document.documentElement.scrollWidth > innerWidth+2," +
            "dialog:!!document.querySelector('[role=dialog]')}))()")
        if measure["overflow"]:
            raise RuntimeError("Actual ProductsPage overflows narrow viewport.")
        return {"real_browser": "Edge headless CDP", "rtl_ar": True,
                "ltr_en": True, "mobile_viewport": measure["width"],
                "keyboard_open": True, "focus_trapped": True,
                "rejected_row_visible": before["rowCount"],
                "accessible_field_reason": True,
                "same_job_ui_correction": True}
    finally:
        if cdp is not None:
            cdp.close()
        if edge is not None and edge[0].poll() is None:
            shared.stop(*edge)
            processes.remove(edge)
        elif edge is not None:
            edge[1].close()
            processes.remove(edge)
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    admin_url = make_url(os.environ["DATABASE_URL_MIGRATION"])
    admin = psycopg.connect(
        admin_url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    processes = []
    token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")
    try:
        ensure_free(5188)
        ensure_free(19226)
        processes.append(shared.start("browser-real-api", "-m",
            "scripts.product_import_phase19_http_selector_server"))
        for role in ("control", "maintenance", "execution"):
            processes.append(shared.start("browser-real-" + role, "-m",
                "domains.simple_products.imports.infrastructure.worker_cli",
                "--role", role))
        with httpx.Client(base_url=shared.BASE, timeout=35,
                          headers={"Authorization": "Bearer " + token}) as client:
            shared.wait_health(client, processes)
            shared.wait_worker(client)
            payload = six_row_fixture()
            admitted = shared.require(client.post("/simple-products/imports",
                data={"request_id": str(uuid4()),
                      "default_lot_control_mode": "NONE",
                      "default_expiry_control_mode": "NONE"},
                files={"file": ("p19-browser-small.csv", payload, "text/csv")}),
                202, "real-browser synthetic admission")
            job = str(admitted["job_id"])
            first = shared.wait_job(client, job,
                valid_states={"COMPLETED_WITH_ERRORS"})
            if (first["imported_rows"], first["invalid_rows"]) != (5, 1):
                raise RuntimeError("Real browser fixture not in 5/1 correction state.")
            initial = _assert_business_evidence(admin, job, 5)
            if initial["invalid"] != 1:
                raise RuntimeError("Unexpected business snapshot before browser.")
            result = browser_journey(token, job, processes)
            final = shared.wait_job(client, job, valid_states={"COMPLETED"})
            if (final["imported_rows"], final["invalid_rows"]) != (6, 0):
                raise RuntimeError("Browser submit failed to correct the real job.")
            evidence = _assert_business_evidence(admin, job, 6)
            if any(evidence.get(key) != 6 for key in
                   ("imported", "price_variants", "audit", "outbox")):
                raise RuntimeError("Actual browser correction produced invalid lineage.")
            print("P19_REAL_BROWSER_RESULT=" + json.dumps(
                {"browser": result, "imported_before": 5, "imported_after": 6,
                 "job_unchanged": final["job_id"] == job, "prices": evidence["price_variants"],
                 "audit": evidence["audit"], "outbox": evidence["outbox"]}), flush=True)
            print("PRODUCT_IMPORT_P19_REAL_BROWSER_BACKEND=PASS", flush=True)
    finally:
        for process, handle in reversed(processes):
            shared.stop(process, handle)
        admin.close()


if __name__ == "__main__":
    main()
