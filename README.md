# PayBooth

Pay-to-unlock screen for dslrBooth (LumaBooth for Windows) using Moyasar.

1. Shows a full-screen QR code for a Moyasar invoice (18 SAR by default).
2. Checks the invoice every 2 s; when it is `paid`, hides itself and starts a dslrBooth print session.
3. dslrBooth sends a `session_end` URL trigger to `http://127.0.0.1:8765` and the screen locks again with a new invoice.

## Setup
1. Download `PayBooth.exe` from Releases into a folder, e.g. `C:\PayBooth`.
2. Copy `config.example.json` to `config.json` next to the exe and fill in:
   - `moyasar_secret_key` (`sk_test_...` for testing, `sk_live_...` for real payments)
   - `dslrbooth_password` (dslrBooth → Settings → General → API)
3. dslrBooth → Settings → General → Triggers → URL trigger: `http://127.0.0.1:8765`
4. Start with Windows: put a shortcut to `PayBooth.exe` in `shell:startup`.

- **Ctrl+Shift+Q** closes PayBooth.
- Without a Moyasar key it runs in mock mode: press **P** to simulate a payment.
- If no `session_end` arrives, it relocks after `session_timeout_seconds` (300).
- Logs: `paybooth.log` next to the exe.

## Build
```
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --noconsole --name PayBooth paybooth.py
```
