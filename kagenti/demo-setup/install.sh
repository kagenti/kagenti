#!/bin/bash
# Must be run from inside kagenti/demo-setup, must be run via source ./install.sh to activate venv
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r ../auth/auth_demo/requirements.txt
