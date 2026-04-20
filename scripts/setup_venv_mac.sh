#!/bin/bash
set -e

# DAWN + T2T Integrated Setup Script (macOS)
# Goal: Single venv for both DAWN and T2T

REPO_ROOT="$(pwd)"
T2T_PATH="$REPO_ROOT/T2T"
VENV_PATH="$REPO_ROOT/.venv"

echo "=== Initializing DAWN + T2T Venv ==="

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing DAWN Core Dependencies..."
# DAWN uses PyYAML for pipelines/links
pip install pyyaml

echo "Installing T2T Dependencies from $T2T_PATH/requirements.txt..."
if [ -f "$T2T_PATH/requirements.txt" ]; then
    pip install -r "$T2T_PATH/requirements.txt"
else
    echo "WARNING: T2T requirements.txt not found at $T2T_PATH/requirements.txt"
fi

echo "=== Verification ==="
python3 <<EOF
import sys
import os

try:
    import yaml
    print("✓ DAWN: yaml imported")
except ImportError:
    print("✗ DAWN: yaml NOT found")

# Check T2T imports
sys.path.insert(0, "$T2T_PATH")
sys.path.insert(0, os.path.join("$T2T_PATH", "src"))

try:
    from src.parser.otp_parser import OTPParser
    print("✓ T2T: src.parser.otp_parser.OTPParser imported")
except ImportError as e:
    print(f"✗ T2T: Import failed - {e}")

EOF

echo "=== Setup Complete ==="
echo "To activate: source .venv/bin/activate"
