# PayBooth – on-site install instructions for Claude

I'm at a client's photo booth. This laptop runs dslrBooth (LumaBooth for Windows)
and is the whole booth (camera + printer attached). One session = one photo, 18 SAR.

## What PayBooth does
`paybooth.py` (built into `PayBooth.exe`) is a fullscreen lock screen:
1. Creates a Moyasar invoice (`POST https://api.moyasar.com/v1/invoices`, amount in halalas, Basic auth with the secret key) and shows its `url` as a QR code.
2. Polls `GET /v1/invoices/{id}` every 2 s until `status` is `paid`.
3. Calls dslrBooth's local API: `http://localhost:1500/api/lockscreen/exit?password=...` then `/api/start?mode=print&password=...`, and hides itself.
4. dslrBooth sends a URL trigger (`?event_type=session_end`) to `http://127.0.0.1:8765` → PayBooth calls `/api/lockscreen/show`, shows itself again with a new invoice.
5. If no `session_end` arrives within `session_timeout_seconds` (300), it relocks anyway.

- Ctrl+Shift+Q closes it. Without a `sk_` key it runs in mock mode (press P to fake a payment).
- Settings: `config.json` next to the exe (copy from `config.example.json`). Logs: `paybooth.log` next to the exe.
- The exe is in the GitHub release: https://github.com/mshraky3/paybooth/releases/tag/v1.0.0
- dslrBooth API endpoints above were confirmed on a real booth; other paths (`/api/showlockscreen`, `/api/lock`, ...) return "Invalid command specified".

## Install plan – help me through these
1. Put `PayBooth.exe` + `config.json` in `C:\PayBooth`.
2. dslrBooth → Settings → General → API: enable it, and test `/api/start?mode=print` with the password.
3. dslrBooth → Settings → General → Triggers: add URL trigger `http://127.0.0.1:8765`. Make sure the print layout takes 1 photo.
4. Fill `dslrbooth_password` in `config.json`.
5. Test the full flow with the Moyasar **test** key (`sk_test_...`) and Moyasar's test card, then switch to the **live** key (`sk_live_...`) and do one real 18 SAR payment.
6. Check the QR screen stays on top of dslrBooth in fullscreen. If not, fix it (e.g. rely on dslrBooth's lock screen, or force foreground).
7. Make PayBooth start with Windows (shortcut in `shell:startup`), after dslrBooth.

If anything breaks, read `paybooth.log`, fix `paybooth.py`, and rebuild:
`pip install -r requirements.txt pyinstaller` then `pyinstaller --onefile --noconsole --name PayBooth paybooth.py`

## Rules
- The owner types the Moyasar keys into `config.json` himself. Don't ask for them in chat, and never commit `config.json`.
- Never enter the owner's Moyasar password anywhere.
