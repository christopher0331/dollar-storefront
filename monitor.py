#!/usr/bin/env python3
"""
On-chain payment monitor for the $1 AI Prompt Pack (ETH).

Strategy (rate-limit resilient, no API key required):
  * PRIMARY: BlockCypher balance API (keyless) — detects inbound deposits
    via balance increase beyond the starting baseline.
  * PRICE: CoinGecko simple price for USD conversion.
  * TXHASH: Ethplorer (best-effort) to attach the confirmation tx hash.

Writes storefront/status.json which the landing page polls.
Exits 0 the moment a qualifying payment (>= $0.90) is detected.
"""
import json, time, urllib.request, urllib.error, os, sys, subprocess

OUR_ADDRESS = "0x6DC71aBB084f6272c34Cc37d59f5bF79826aB24d"
OUR_LOWER   = OUR_ADDRESS.lower()
HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(HERE, "status.json")
REPO_DIR = HERE  # this folder IS the github-pages repo (dollar-storefront)

BLOCKCYPHER = "https://api.blockcypher.com/v1/eth/main/addrs/%s/balance" % OUR_ADDRESS
COINGECKO   = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
ETHPLORER   = "https://api.ethplorer.io/getAddressTransactions/%s?apiKey=freekey&limit=10" % OUR_LOWER

USD_THRESHOLD = 0.90
MIN_ETH = 0.00040          # ~$0.77 at $1925; combined with USD check
POLL_SECONDS = 30
UA = {"User-Agent": "revenue-monitor/1.0"}

def get_json(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(2 + i * 2)
    raise last

def eth_price():
    try:
        return float(get_json(COINGECKO)["ethereum"]["usd"])
    except Exception:
        return 1926.0

def balance_eth():
    d = get_json(BLOCKCYPHER)
    return int(d.get("balance", 0)) / 1e18

def find_txhash():
    """Best-effort: newest inbound tx to us in the window."""
    try:
        txs = get_json(ETHPLORER) or []
        for tx in txs:
            if (tx.get("to") or "").lower() == OUR_LOWER:
                return tx.get("hash")
    except Exception:
        pass
    return None

def write_status(data):
    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATUS_FILE)
    sync_status(data)

_last_pushed = ""

def sync_status(data):
    """Push status.json to the GitHub Pages repo so the public page reflects
    live state. Only commits when content changed (no commit spam)."""
    global _last_pushed
    payload = json.dumps(data, sort_keys=True)
    if payload == _last_pushed:
        return
    _last_pushed = payload
    try:
        env = dict(os.environ)
        subprocess.run(["git", "-C", REPO_DIR, "add", "status.json"],
                       check=True, capture_output=True, env=env, timeout=30)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m",
                        "monitor: update status.json"],
                       check=True, capture_output=True, env=env, timeout=30)
        subprocess.run(["git", "-C", REPO_DIR, "push", "origin", "main"],
                       check=True, capture_output=True, env=env, timeout=60)
        print("[monitor] status.json synced to GitHub Pages")
    except Exception as e:
        # non-fatal: page display is secondary to on-chain detection
        print(f"[monitor] sync skipped: {e}")

def main():
    price = eth_price()
    baseline = balance_eth()
    START = time.strftime("%H:%M:%S")
    write_status({"received": False, "last_checked": START, "address": OUR_ADDRESS,
                  "baseline_eth": f"{baseline:.8f}"})
    print(f"[monitor] START {START} eth=${price:.2f} baseline={baseline:.8f} ETH threshold=${USD_THRESHOLD}")

    while True:
        try:
            price = eth_price()
            bal = balance_eth()
            now = time.strftime("%H:%M:%S")
            delta = bal - baseline
            usd = delta * price
            if delta >= MIN_ETH and usd >= USD_THRESHOLD:
                h = find_txhash()
                print(f"[monitor] *** PAYMENT CONFIRMED *** +{delta:.6f} ETH (~${usd:.2f}) tx={h}")
                write_status({"received": True,
                              "amount_eth": f"{delta:.6f}",
                              "usd_value": f"{usd:.2f}",
                              "txhash": h or "",
                              "last_checked": now,
                              "address": OUR_ADDRESS})
                print("[monitor] MISSION COMPLETE — $1 received. Exiting.")
                sys.exit(0)
            print(f"[monitor] {now} bal={bal:.8f} (+{delta:.8f} ETH ~${usd:.2f}) — watching")
            write_status({"received": False, "last_checked": now, "address": OUR_ADDRESS,
                          "baseline_eth": f"{baseline:.8f}"})
        except Exception as e:
            print(f"[monitor] cycle error: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
