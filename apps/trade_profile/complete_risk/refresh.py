"""refresh.py — see the package docstring."""
import subprocess
import bootstrap

def fetch_extended_hours_prices():
    """Step 1: Fetch latest prices from all sources."""
    print("=" * 100)
    print("STEP 1: Fetching Real-Time Extended Hours Prices")
    print("=" * 100)
    result = subprocess.run([
        "uv", "run", "--with-editable", str(bootstrap.ROOT.parent / "data_providers"), "--no-project", "--with", "duckdb", "--with", "ib_async",
        "--with", "yfinance", "--with", "futu-api", "--with", "alpaca-py",
        "python", str(bootstrap.ROOT / "apps/data_ops/fetch_extended_hours_prices.py")
    ], cwd=str(bootstrap.ROOT))
    return result.returncode == 0
