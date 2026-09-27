#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
export DEMO_MODE=1
python3 bot.py
