#!/usr/bin/env python3
"""
Direct CLI and script entrypoint for Perplexity Search.
Usage:
    python perplexity_search.py "What are the key features introduced in Python 3.14?"
    python perplexity_search.py "your query" --json
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.swarm_sdk.search.perplexity import cli_main

if __name__ == "__main__":
    cli_main()
