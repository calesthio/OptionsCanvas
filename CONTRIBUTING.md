# Contributing

Thanks for your interest. This is a small, opinionated codebase — keep changes focused and the bar for new dependencies high.

## Ground rules

- **Match the existing patterns.** Especially:
  - All broker calls go through `BrokerInterface` — never import Alpaca SDK from outside `alpaca_broker.py`.
  - Order/position lifecycle changes go through the state machines in `state_machine.py`.
  - The broker (not the database) is the source of truth for option chain details (expirations, strikes, increments).
- **No secrets in commits.** `config/config.json` and anything under `state/` are gitignored — keep them that way.
- **Keep the SL/TP-stays-local invariant.** Server-side SL/TP detection (see `trading_engine.py::check_stop_loss` / `check_take_profit`) is a load-bearing differentiator. Don't add code paths that submit stop orders to the broker as resting orders without a very strong reason and a discussion in an issue first.

## Running tests before you push

```bash
pytest tests/unit tests/property -q
node --test tests/frontend
# browser regression (requires the platform running on :5001)
npx playwright test tests/browser/chart_trading.spec.js
```

## Pull request checklist

- [ ] Branch is up to date with `main`.
- [ ] Tests added / updated for the behavior you changed.
- [ ] All test suites pass locally.
- [ ] No new runtime dependency, or a brief justification in the PR body.
- [ ] No secrets, no real API keys, no `state/*.db` artifacts.
- [ ] README / docs/ARCHITECTURE.md updated if you changed user-visible behavior or module boundaries.
- [ ] PR description explains the *why*, not just the *what*.

## Reporting bugs

Open an issue with: platform (OS + Python version), exact command run, expected vs. actual behavior, and the relevant section of `assisted_trading/logs/` (with API keys redacted).

## License

By contributing you agree your contributions are licensed under AGPL-3.0-or-later, matching the project license.
