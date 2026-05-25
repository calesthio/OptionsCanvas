# Testing Infrastructure

## Quick Start

Run all tests:
```bash
pytest tests/ -v
```

Run specific test types:
```bash
# Unit tests only (fast)
pytest tests/unit/ -v -m unit

# Property tests (hypothesis)
pytest tests/property/ -v -m property

# Simulation tests (slow)
pytest tests/simulation/ -v -m simulation
```

## Test Coverage

Generate coverage report:
```bash
pytest tests/ --cov=assisted_trading/backend --cov-report=html
open tests/reports/coverage/index.html
```

## Property Testing Profiles

- **dev** (default): 100 examples per test
- **ci**: 10 examples per test (fast for CI)
- **thorough**: 10,000 examples per test (nightly)

Select profile:
```bash
pytest tests/property/ --hypothesis-profile=thorough
```

## Documentation

- [Rock Solid Plan](../ROCK_SOLID_PLAN.md) - Comprehensive testing strategy
- [Implementation Guide](../IMPLEMENTATION_GUIDE.md) - Step-by-step setup
- [State Machines](../docs/STATE_MACHINES.md) - State machine diagrams and invariants
