from __future__ import annotations

from io import StringIO

import pandas as pd
import requests


WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_current_constituents() -> pd.DataFrame:
    """Fetch the current S&P 500 constituents from Wikipedia.

    Wikipedia tickers use dots for share classes (BRK.B). yfinance expects
    dashes (BRK-B), so normalize symbols before returning.
    """
    # pd.read_html(url) hands the request to bare urllib, which on some Python
    # installs (notably python.org builds on macOS) doesn't pick up certifi's
    # CA bundle and fails SSL verification. requests does, so fetch the HTML
    # ourselves and hand the text to read_html instead of the URL.
    response = requests.get(WIKIPEDIA_SP500_URL, timeout=30, headers={"User-Agent": "quantbench/0.1"})
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    if not tables:
        raise ValueError("Wikipedia returned no tables for S&P 500 constituents")

    table = tables[0].copy()
    required = {"Symbol", "Security"}
    missing = required.difference(table.columns)
    if missing:
        raise ValueError(f"S&P 500 table missing required columns: {sorted(missing)}")

    table["Symbol"] = table["Symbol"].astype(str).str.replace(".", "-", regex=False).str.strip()
    table["Security"] = table["Security"].astype(str).str.strip()
    return table
