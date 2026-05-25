# Third-Party Notices

OptionsCanvas depends on the following open-source components. Each is used
under the terms of its respective license. Copyright and notice text below is
reproduced verbatim from the upstream projects where required.

---

## Frontend libraries (loaded via CDN at runtime)

### Lightweight Charts™
- **Project**: https://github.com/tradingview/lightweight-charts
- **License**: Apache License, Version 2.0
- **Notice** *(reproduced from upstream `NOTICE` file as required by Apache-2.0 §4(d))*:
  ```
  TradingView Lightweight Charts™
  Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/
  ```
- Full license text: https://github.com/tradingview/lightweight-charts/blob/master/LICENSE

> "TradingView" and "Lightweight Charts" are trademarks of TradingView, Inc.
> They are referenced in this project's documentation only for descriptive
> attribution of the upstream component, per Apache-2.0 §6.

### Socket.IO Client
- **Project**: https://github.com/socketio/socket.io-client
- **License**: MIT
- Full license text: https://github.com/socketio/socket.io-client/blob/main/LICENSE

---

## Backend Python dependencies (direct)

The full transitive dependency tree is resolved by `pip` from `requirements.txt`
at install time. Each package retains its own license file inside the installed
distribution. Direct dependencies and their licenses:

| Package | License | Project |
|---|---|---|
| Flask | BSD-3-Clause | https://github.com/pallets/flask |
| Flask-CORS | MIT | https://github.com/corydolphin/flask-cors |
| Flask-SocketIO | MIT | https://github.com/miguelgrinberg/Flask-SocketIO |
| python-socketio | MIT | https://github.com/miguelgrinberg/python-socketio |
| python-engineio | MIT | https://github.com/miguelgrinberg/python-engineio |
| alpaca-py | Apache-2.0 | https://github.com/alpacahq/alpaca-py |
| pytz | MIT | https://launchpad.net/pytz |
| requests | Apache-2.0 | https://github.com/psf/requests |

---

## How attribution is maintained

- This `THIRD_PARTY_NOTICES.md` file is shipped in every distribution
  (source archive, ZIP, Docker image).
- The Apache-2.0 NOTICE text from Lightweight Charts is reproduced verbatim
  above; modifying it is forbidden by the license.
- OptionsCanvas itself is licensed under AGPL-3.0-or-later (see [`LICENSE`](LICENSE)).
- Trademarks of upstream projects (notably "TradingView" and "Lightweight Charts")
  are not used in the marketing of OptionsCanvas. They appear only in
  technical/origin context (e.g. "uses TradingView Lightweight Charts").
