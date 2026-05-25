# Symbol Management Scripts

Database management scripts for onboarding and managing trading symbols.

All option chain details (expirations, strikes, increments) are fetched from the
broker API at runtime. The database only stores which symbols are enabled.

## Available Scripts

### onboard_symbol.py (Recommended)
Onboard symbols — just provide the ticker. Verifies options exist on Alpaca,
then inserts into the database.

**Usage:**
```bash
# Onboard a single symbol
python scripts/onboard_symbol.py AAPL

# Onboard multiple symbols at once
python scripts/onboard_symbol.py AAPL MSFT NVDA TSLA

# List all symbols in database
python scripts/onboard_symbol.py --list
```

### onboard_symbols.py (Batch)
Bulk onboard from a predefined list. Edit `SYMBOLS_TO_ONBOARD` in the script.

**Usage:**
```bash
python scripts/onboard_symbols.py
```

### offboard_symbols.py
Remove symbols from the trading database (soft delete by marking inactive).

**Usage:**
```bash
# List all symbols
python scripts/offboard_symbols.py --list

# Interactive mode
python scripts/offboard_symbols.py --interactive

# Hard delete (permanent, use with caution)
python scripts/offboard_symbols.py --hard-delete
```

### verify_setup.py
Verify database setup and display all configured symbols.

**Usage:**
```bash
python scripts/verify_setup.py
```

### example_onboard.py
Reference file with common symbol groups (starter pack, sector ETFs, etc.)

## Database Location

All scripts use the database at:
```
assisted_trading/state/trading.db
```

## Notes

- Symbols are soft-deleted (marked inactive) by offboard script
- The `supported_symbols` table only stores: symbol, is_active, notes, timestamps
- All option configuration is derived from the broker API at runtime
- Scripts are idempotent — safe to run multiple times
