"""
PayBooth - locks dslrBooth behind a Moyasar payment.

Flow: create Moyasar invoice -> show QR full-screen -> poll until paid ->
hide screen + start dslrBooth print session -> dslrBooth "session_end"
trigger -> lock again with a fresh invoice.

Operator exit: Ctrl+Shift+Q.  Mock mode (no key): press P to fake a payment.
"""
import base64
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import arabic_reshaper
import qrcode
from bidi.algorithm import get_display
from PIL import ImageTk

BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "moyasar_secret_key": "",
    "amount_halalas": 1800,
    "currency": "SAR",
    "description": "Muse Booth - 1 photo",
    "success_url": "",
    "dslrbooth_url": "http://localhost:1500",
    "dslrbooth_password": "",
    "dslrbooth_mode": "print",
    "trigger_port": 8765,
    "poll_seconds": 2,
    "session_timeout_seconds": 300,
}

logging.basicConfig(
    filename=os.path.join(BASE_DIR, "paybooth.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("paybooth")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return {**DEFAULT_CONFIG, **json.load(f)}


def ar(text):
    return get_display(arabic_reshaper.reshape(text))


# ---------------------------------------------------------------- Moyasar

class Moyasar:
    API = "https://api.moyasar.com/v1/invoices"

    def __init__(self, cfg):
        self.cfg = cfg
        self.mock = not cfg["moyasar_secret_key"].startswith("sk_")
        self._mock_paid = False
        token = base64.b64encode(f'{cfg["moyasar_secret_key"]}:'.encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def _call(self, method, url, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def create_invoice(self):
        if self.mock:
            self._mock_paid = False
            return {"id": f"mock-{int(time.time())}", "url": "https://moyasar.com/mock-invoice", "status": "initiated"}
        body = {
            "amount": int(self.cfg["amount_halalas"]),
            "currency": self.cfg["currency"],
            "description": self.cfg["description"],
            "metadata": {"source": "paybooth"},
        }
        if self.cfg["success_url"]:
            body["success_url"] = self.cfg["success_url"]
        return self._call("POST", self.API, body)

    def status(self, invoice_id):
        if self.mock:
            return "paid" if self._mock_paid else "initiated"
        return self._call("GET", f"{self.API}/{invoice_id}")["status"]


# ---------------------------------------------------------------- dslrBooth

class DslrBooth:
    def __init__(self, cfg):
        self.cfg = cfg

    def _get(self, path, **params):
        if not self.cfg["dslrbooth_password"]:
            log.info("dslrBooth (no password set, skipped): %s", path)
            return
        params["password"] = self.cfg["dslrbooth_password"]
        url = f'{self.cfg["dslrbooth_url"]}{path}?{urllib.parse.urlencode(params)}'
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                log.info("dslrBooth %s -> %s", path, r.read()[:200])
        except Exception as e:  # best effort: never crash the lock screen
            log.warning("dslrBooth %s failed: %s", path, e)

    def lock(self):
        self._get("/api/lockscreen/show")

    def start_session(self):
        self._get("/api/lockscreen/exit")
        self._get("/api/start", mode=self.cfg["dslrbooth_mode"])


# ---------------------------------------------------------------- trigger listener

def start_trigger_server(port, events):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            event = qs.get("event_type", [""])[0]
            log.info("trigger: %s", event)
            events.put(event)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        do_POST = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


# ---------------------------------------------------------------- UI

class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.moyasar = Moyasar(cfg)
        self.booth = DslrBooth(cfg)
        self.events = queue.Queue()
        self.invoice = None
        self.locked = False
        self.session_started_at = 0.0
        self.busy = False

        self.root = tk.Tk()
        self.root.title("PayBooth")
        self.root.configure(bg="#111111", cursor="none")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.bind("<Control-Shift-Q>", lambda e: self.root.destroy())
        self.root.bind("<Control-Shift-q>", lambda e: self.root.destroy())
        if self.moyasar.mock:
            self.root.bind("<p>", lambda e: setattr(self.moyasar, "_mock_paid", True))

        price = f'{self.cfg["amount_halalas"] / 100:g} {self.cfg["currency"]}'
        frame = tk.Frame(self.root, bg="#111111")
        frame.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(frame, text=ar("امسح الكود للدفع"), font=("Tahoma", 40, "bold"), fg="white", bg="#111111").pack(pady=(0, 4))
        tk.Label(frame, text="Scan to pay", font=("Segoe UI", 26), fg="#bbbbbb", bg="#111111").pack(pady=(0, 20))
        self.qr_label = tk.Label(frame, bg="white", bd=0)
        self.qr_label.pack()
        tk.Label(frame, text=price, font=("Segoe UI", 34, "bold"), fg="white", bg="#111111").pack(pady=(20, 4))
        self.status = tk.Label(frame, text="", font=("Tahoma", 20), fg="#bbbbbb", bg="#111111")
        self.status.pack()
        if self.moyasar.mock:
            tk.Label(self.root, text="MOCK MODE - press P to simulate payment", font=("Segoe UI", 14),
                     fg="#ff6666", bg="#111111").place(relx=0.5, rely=0.97, anchor="s")

        start_trigger_server(int(cfg["trigger_port"]), self.events)
        self.lock()
        self.root.after(500, self.tick)

    # -- state changes

    def lock(self):
        self.locked = True
        self.booth.lock()
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.new_invoice()

    def unlock(self):
        log.info("PAID invoice %s -> starting session", self.invoice["id"])
        self.locked = False
        self.invoice = None
        self.session_started_at = time.time()
        self.root.withdraw()
        self.booth.start_session()

    def new_invoice(self):
        self.status.config(text=ar("جاري التجهيز..."))
        self.qr_label.config(image="")
        self.run_bg(self.moyasar.create_invoice, self.on_invoice)

    def on_invoice(self, inv, err):
        if err:
            log.error("create invoice failed: %s", err)
            self.status.config(text=ar("خطأ في الاتصال، إعادة المحاولة..."))
            self.root.after(5000, self.new_invoice)
            return
        self.invoice = inv
        log.info("invoice %s %s", inv["id"], inv["url"])
        img = qrcode.make(inv["url"], box_size=12, border=2).get_image()
        size = int(min(self.root.winfo_screenwidth(), self.root.winfo_screenheight()) * 0.45)
        self.qr_img = ImageTk.PhotoImage(img.resize((size, size)))
        self.qr_label.config(image=self.qr_img)
        self.status.config(text="")

    # -- loop

    def run_bg(self, fn, done, *args):
        def worker():
            try:
                res, err = fn(*args), None
            except Exception as e:
                res, err = None, e
            self.root.after(0, lambda: done(res, err))
        threading.Thread(target=worker, daemon=True).start()

    def tick(self):
        while not self.events.empty():
            event = self.events.get()
            if event == "session_end" and not self.locked:
                self.lock()

        if self.locked:
            self.root.attributes("-topmost", True)
            self.root.lift()
            if self.invoice and not self.busy:
                self.busy = True
                self.run_bg(self.moyasar.status, self.on_status, self.invoice["id"])
        elif time.time() - self.session_started_at > float(self.cfg["session_timeout_seconds"]):
            log.warning("no session_end received, relocking after timeout")
            self.lock()

        self.root.after(int(float(self.cfg["poll_seconds"]) * 1000), self.tick)

    def on_status(self, status, err):
        self.busy = False
        if err:
            log.warning("status check failed: %s", err)
            return
        if not self.locked or not self.invoice:
            return
        if status == "paid":
            self.unlock()
        elif status in ("expired", "canceled", "failed", "voided"):
            log.info("invoice %s is %s, creating a new one", self.invoice["id"], status)
            self.new_invoice()


if __name__ == "__main__":
    App(load_config()).root.mainloop()
