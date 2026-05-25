#!/usr/bin/env bash
# ============================================================================
# OptionsCanvas — Double-click launcher for macOS / Linux
# First run: creates a venv, installs deps, launches the platform.
# Subsequent runs: just launches the platform.
#
# Make executable once:   chmod +x optionscanvas.sh
# Run:                    ./optionscanvas.sh
# (On macOS you can also right-click → Open With → Terminal.)
# ============================================================================

set -e

# Switch to the script's directory regardless of where it was launched from.
cd "$(dirname "$0")"

printf '\n============================================================\n'
printf '  OptionsCanvas — starting up\n'
printf '============================================================\n\n'

# ---- 1. Locate Python ------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    cat <<'EOF'
[ERROR] Python is not installed or not on PATH.

Install Python 3.10 or newer:
  • macOS:  brew install python    (or https://www.python.org/downloads/)
  • Linux:  sudo apt install python3 python3-venv python3-pip
            (Debian/Ubuntu — use your distro's package manager)

Then re-run this script.
EOF
    exit 1
fi

# Sanity-check version (need 3.10+).
"$PY" - <<'PYV'
import sys
if sys.version_info < (3, 10):
    sys.stderr.write(f"[ERROR] Python {sys.version_info.major}.{sys.version_info.minor} found, need 3.10+\n")
    sys.exit(1)
PYV

# ---- 2. Create venv on first run ------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "[first-run] Creating virtual environment in .venv ..."
    "$PY" -m venv .venv
    echo
fi

# ---- 3. Activate venv -----------------------------------------------------
# shellcheck disable=SC1091
source .venv/bin/activate

# ---- 4. Install / update deps on first run --------------------------------
if [ ! -f ".venv/.deps_installed" ]; then
    echo "[first-run] Installing Python dependencies (this takes ~2 min) ..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    touch .venv/.deps_installed
    echo
    echo "[first-run] Dependencies installed."
    echo
fi

# ---- 5. Launch the platform -----------------------------------------------
echo "Launching OptionsCanvas ... your browser will open at http://localhost:5001"
echo "(Press Ctrl+C to stop the platform.)"
echo

exec python assisted_trading/run_platform.py
