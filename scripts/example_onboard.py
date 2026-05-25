#!/usr/bin/env python3
"""
Example Symbol Onboarding
Quick reference for common symbol groups.

Usage:
    Just run: python scripts/onboard_symbol.py SPY QQQ AAPL NVDA
    Or edit SYMBOLS_TO_ONBOARD in scripts/onboard_symbols.py
"""

# ============================================================================
# STARTER PACK - Most Popular Symbols
# ============================================================================

STARTER_PACK = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA']

# ============================================================================
# DAILY EXPIRATION ETFs
# ============================================================================

DAILY_ETFS = ['SPY', 'QQQ', 'IWM', 'DIA']

# ============================================================================
# HIGH-LIQUIDITY STOCKS
# ============================================================================

HIGH_LIQUIDITY_STOCKS = [
    'NVDA', 'TSLA', 'AAPL', 'MSFT', 'META', 'AMZN', 'GOOGL', 'NFLX',
]

# ============================================================================
# SEMICONDUCTOR STOCKS
# ============================================================================

SEMICONDUCTORS = ['NVDA', 'AMD', 'INTC', 'MU', 'AVGO', 'QCOM', 'TSM']

# ============================================================================
# SECTOR ETFs
# ============================================================================

SECTOR_ETFS = ['XLF', 'XLE', 'XLK', 'XLV', 'XBI', 'XLP', 'XLI', 'XLU']

# ============================================================================
# VOLATILITY / HEDGE PRODUCTS
# ============================================================================

VOLATILITY_PRODUCTS = ['VXX', 'UVXY', 'SVXY']

# ============================================================================
# INTERNATIONAL ETFs
# ============================================================================

INTERNATIONAL_ETFS = ['FXI', 'EEM', 'EWZ', 'KWEB', 'MCHI']

# ============================================================================
# USAGE INSTRUCTIONS
# ============================================================================

print("""
===================================================================
  Example Symbol Groups
===================================================================

To onboard symbols, just run:

    python scripts/onboard_symbol.py SPY QQQ AAPL NVDA TSLA

All option chain details (expirations, strikes, increments) are
fetched from the broker API at runtime. No manual configuration needed.

Available symbol groups in this file:
  STARTER_PACK          SPY, QQQ, AAPL, MSFT, NVDA, TSLA
  DAILY_ETFS            SPY, QQQ, IWM, DIA
  HIGH_LIQUIDITY_STOCKS NVDA, TSLA, AAPL, MSFT, META, AMZN, ...
  SEMICONDUCTORS        NVDA, AMD, INTC, MU, AVGO, QCOM, TSM
  SECTOR_ETFS           XLF, XLE, XLK, XLV, XBI, ...
  VOLATILITY_PRODUCTS   VXX, UVXY, SVXY
  INTERNATIONAL_ETFS    FXI, EEM, EWZ, KWEB, MCHI

To use a group, edit scripts/onboard_symbols.py and set:
  SYMBOLS_TO_ONBOARD = ['SPY', 'QQQ', ...]

===================================================================
""")
