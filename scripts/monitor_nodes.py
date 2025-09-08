#!/usr/bin/env python3
"""
Monitor per-node capture rates in near real time.

Usage:
  ./scripts/monitor_nodes.py
  ./scripts/monitor_nodes.py --db ~/wifi_promiscuous/data/captures.sqlite --window 10 --interval 1 --nodes 12
"""
import argparse
import os
import sqlite3
import time
from datetime import datetime, timezone

DEF_DB = os.path.expanduser("~/wifi_promiscuous/data/captures.sqlite")

def parse_args():
    ap = argparse.ArgumentParser(description="Live per-node Wi-Fi capture monitor")
    ap.add_argument("--db", default=DEF_DB, help="Path to captures.sqlite")
    ap.add_argument("--window", type=int, default=10, help="Sliding window (seconds) for counts/rates")
    ap.add_argument("--interval", type=float, default=1.0, help="Refresh interval (seconds)")
    ap.add_argument("--nodes", type=int, default=12, help="Expected number of nodes (1..N)")
    ap.add_argument("--clear", action="store_true", help="Clear screen on each refresh")
    return ap.parse_args()

def fetch_stats(conn, window_s):
    # Count and last-seen age (seconds) per node in a single query
    sql = """
    SELECT
      node_id,
      COUNT(*) AS cnt,
      (julianday('now') - MAX(julianday(ts_utc))) * 86400.0 AS age_s
    FROM wifi_captures
    WHERE julianday(ts_utc) >= julianday('now', ?)
    GROUP BY node_id
    """
    # window string like "-10 seconds"
    window_expr = f"-{int(window_s)} seconds"
    cur = conn.execute(sql, (window_expr,))
    rows = cur.fetchall()
    cur.close()
    return rows

def fmt_rate(cnt, window_s):
    return cnt / window_s if window_s > 0 else 0.0

def bar(rate, scale=1.0, width=30):
    # Simple ASCII bar; scale controls how many Hz per char
    n = int(min(width, max(0, rate / scale)))
    return "█" * n + " " * (width - n)

def main():
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA query_only=TRUE;")

    # Determine autoscale for the bar based on first sample
    scale = 1.0  # 1 sample/s per block by default
    first = True

    try:
        while True:
            if args.clear:
                # Clear screen (portable-ish)
                os.system("clear" if os.name != "nt" else "cls")

            rows = fetch_stats(conn, args.window)
            # Build dictionary {node_id: (cnt, age_s)}
            stats = {int(r[0]): (int(r[1]), float(r[2] if r[2] is not None else 1e9)) for r in rows}

            # Autoscale on first pass: find a typical nonzero rate
            if first:
                nonzero = [fmt_rate(c, args.window) for (_, (c, _)) in stats.items() if c > 0]
                if nonzero:
                    # put about ~20 blocks for typical rate
                    typical = sorted(nonzero)[len(nonzero)//2]
                    scale = max(typical / 20.0, 0.2)  # clamp to something sane
                first = False

            # Header
            now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            print(f"Wi-Fi Capture Monitor  |  window={args.window}s  interval={args.interval}s  UTC={now}")
            print("-" * 78)
            print(f"{'Node':>4}  {'Count':>6}  {'Rate/s':>7}  {'Last Seen (s)':>12}  {'Activity':<30}")
            print("-" * 78)

            total = 0
            missing = []
            for node in range(1, args.nodes + 1):
                cnt, age = stats.get(node, (0, float('inf')))
                rate = fmt_rate(cnt, args.window)
                total += cnt
                if cnt == 0 and age == float('inf'):
                    missing.append(node)
                    age_display = "—"
                else:
                    age_display = f"{age:5.1f}"
                print(f"{node:>4}  {cnt:>6}  {rate:7.2f}  {age_display:>12}  {bar(rate, scale=scale)}")

            print("-" * 78)
            print(f"Total in window: {total}   Missing nodes: {missing if missing else 'None'}")
            print("Hints: If a node is consistently missing, check USB cabling, power, and channel mapping.")

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nExiting monitor.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
