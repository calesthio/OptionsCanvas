# Architecture

High-level map of how the OptionsCanvas platform is wired. Read this with the source tree open; file paths are clickable cues, not exhaustive.

## Topology

```
 ┌─────────────────────────────────────────────────────────────┐
 │  Browser (vanilla JS, Lightweight Charts)                   │
 │  ┌──────────────┐  ┌──────────────────────┐                 │
 │  │ ChartManager │◄─┤ OrderPanelOnChart    │  drag pills     │
 │  │              │  │ (Buy / SL / TP)      │                 │
 │  └──────┬───────┘  └──────────┬───────────┘                 │
 │         │                     │                             │
 │         ▼                     ▼                             │
 │  ┌────────────────────────────────────────┐                 │
 │  │ ChartTradingController (state bridge)  │                 │
 │  └────────────┬───────────────────────────┘                 │
 │               ▼                                             │
 │  ┌────────────────────────┐   ┌───────────────────────┐     │
 │  │ TradingPanel (side)    │   │ BlackScholesCalculator│     │
 │  │ contract / size / btn  │   │ premium + P&L proj.   │     │
 │  └────────────┬───────────┘   └───────────────────────┘     │
 └───────────────┼─────────────────────────────────────────────┘
                 │ REST + Socket.IO (port 5001)
                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Flask backend (assisted_trading/backend/)                  │
 │  ┌────────────────────┐                                     │
 │  │ chart_api_server   │  REST + WS endpoints                │
 │  └─────────┬──────────┘                                     │
 │            ▼                                                │
 │  ┌────────────────────┐  uses  ┌──────────────────────┐     │
 │  │ trading_engine     │───────►│ broker_interface     │     │
 │  │ entry / monitor /  │        │  (abstract)          │     │
 │  │ SL & TP breach     │        └──────────┬───────────┘     │
 │  └─────┬──────┬───────┘                   ▼                 │
 │        │      │                  ┌──────────────────┐       │
 │        ▼      ▼                  │ alpaca_broker    │──► Alpaca paper API
 │  ┌──────────┐ ┌────────────────┐ └──────────────────┘       │
 │  │ order_   │ │ position_      │                            │
 │  │ manager  │ │ manager_v2     │                            │
 │  └────┬─────┘ └────┬───────────┘                            │
 │       ▼            ▼                                        │
 │  ┌────────────────────────┐                                 │
 │  │ SQLite (state/trading.db)                                │
 │  │ + state_machine invariants                               │
 │  └────────────────────────┘                                 │
 └─────────────────────────────────────────────────────────────┘
```

## Frontend modules

`assisted_trading/frontendv2/js/`

- **`chart/ChartManager.js`** — wraps the Lightweight Charts instance, owns the price series and indicator overlays.
- **`chart/OrderPanelOnChart.js`** — renders the Buy / SL / TP pills on the chart, manages persistent price lines, hit areas, and the limit-trigger flip when Buy is dragged off live price. Computes projected P&L via `BlackScholesCalculator`.
- **`chart/ChartTradingController.js`** — readiness state machine. The on-chart panel queries this for `getState().ready` before enabling Buy.
- **`chart/PriceLineManager.js`, `DragHandles.js`, `DrawingManager.js`, `IndicatorsManager.js`, `PositionPanelOnChart.js`, `ContextMenu.js`** — supporting chart pieces.
- **`trading/TradingPanel.js`** — right-hand side panel: symbol, expiration, strike, contract count, premium, place-order button.
- **`trading/BracketOrderDrawer.js`, `OrderTracker.js`, `PositionTracker.js`** — bracket-entry UI and live order/position state mirrors.
- **`utils/BlackScholesCalculator.js`** — option premium projection used during SL/TP drag.
- **`utils/TechnicalIndicators.js`** — VWAP / SMA / EMA / RSI math.
- **`main.js`** — composition root; wires the modules together and starts the WS stream.

## Backend modules

`assisted_trading/backend/`

- **`chart_api_server.py`** — Flask app + Socket.IO. Routes for chart data, contract lookup, order placement, position queries.
- **`trading_engine.py`** — central loop.
  - Order placement (`place_buy_order`, equity-limit queue).
  - Fill monitoring (`monitor_order_fill`).
  - **Server-side SL/TP**: `check_stop_loss()` and `check_take_profit()` compare the live underlying quote against levels stored on the position record; on breach they call `close_position()` which submits a market sell. Stops never live as broker-resting orders.
- **`order_manager.py`** — order CRUD on SQLite, transitions via `OrderStateMachine`.
- **`position_manager_v2.py`** — open / update / close positions; persists SL/TP fields.
- **`state_machine.py`** — formal `OrderState` and `PositionState` machines with declared valid transitions + `InvariantValidator`.
- **`broker_interface.py`** — abstract broker contract: place_market_order, place_limit_order, get_order_status, get_option_chain, get_available_expirations, etc.
- **`alpaca_broker.py`** — concrete Alpaca implementation; data-driven strike increment with 1-hour cache; expiration discovery.
- **`contract_validator.py`** — validates symbol / DTE / strike against the broker.
- **`symbol_config_service.py`** — manages the (intentionally tiny) `supported_symbols` table.
- **`market_hours.py`** — RTH gating.
- **`database/db_manager.py`** — SQLite bootstrap + the auto-migration from the old 15-column `supported_symbols` schema to the new 6-column one.

## Process boundaries

- One Python process (Flask + SocketIO) on `127.0.0.1:5001`.
- One SQLite file at `assisted_trading/state/trading.db`.
- One outbound integration: the Alpaca REST/WS endpoints configured in `config/config.json`.

## Extending

- **New broker**: implement `BrokerInterface`, swap construction in `chart_api_server.initialize_services`.
- **New indicator**: add to `utils/TechnicalIndicators.js` and register in `IndicatorsManager.js`.
- **New order type**: extend `OrderState` valid transitions in `state_machine.py`, add the placement path in `trading_engine.py`, surface it in `OrderPanelOnChart.js` / `TradingPanel.js`.
