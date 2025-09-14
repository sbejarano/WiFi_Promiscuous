# monitor.py - Rich-based live console for Wi-Fi and GPS monitoring

from rich.live import Live
from rich.table import Table
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich import box
import sqlite3
import time
from datetime import datetime

DB_PATH = "./data/captures.sqlite"
REFRESH_INTERVAL = 3  # seconds

console = Console()

def get_latest_captures():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT ts_utc, node_id, bssid, 
                   COALESCE(NULLIF(ssid,''),'(hidden)') AS ssid,
                   rssi_dbm, channel, frequency_mhz,
                   gps_lat, gps_lon, gps_alt_m, gps_speed_mps, gps_track_deg
            FROM wifi_captures
            WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL
              AND gps_lat != 0 AND gps_lon != 0
            ORDER BY ts_utc DESC
            LIMIT 100;
        """)
        return cur.fetchall()

def build_device_table(rows):
    table = Table(title="Live Wi-Fi Captures", box=box.SIMPLE_HEAVY)
    columns = ["Timestamp", "Node", "BSSID", "SSID", "RSSI", "Channel", "Freq", 
               "Lat", "Lon", "Alt", "Speed", "Heading"]
    for col in columns:
        table.add_column(col, style="cyan" if col in ("BSSID", "SSID") else "white")

    for row in rows:
        table.add_row(
            row["ts_utc"],
            str(row["node_id"]),
            row["bssid"],
            row["ssid"],
            str(row["rssi_dbm"]),
            str(row["channel"]),
            str(row["frequency_mhz"]),
            f"{row['gps_lat']:.6f}",
            f"{row['gps_lon']:.6f}",
            f"{row['gps_alt_m'] or 0:.1f}",
            f"{row['gps_speed_mps'] or 0:.1f}",
            f"{row['gps_track_deg'] or 0:.1f}"
        )

    return table

def build_status_panel(gps_ok: bool, node_count: int):
    status = Text()
    status.append("GPS: ", style="bold")
    status.append("LOCKED\n", style="green" if gps_ok else "red")

    status.append(f"Nodes: {node_count}\n", style="bold magenta")
    status.append("Updated: " + datetime.utcnow().strftime("%H:%M:%S UTC"), style="bold")

    return Panel(status, title="System Status", border_style="bright_blue")

def get_node_status():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT node_id) FROM wifi_captures")
        nodes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wifi_captures WHERE gps_lat != 0 AND gps_lon != 0")
        gps_valid = cur.fetchone()[0] > 0
        return gps_valid, nodes

def main():
    layout = Layout()
    layout.split_column(
        Layout(name="upper", ratio=4),
        Layout(name="lower", ratio=1),
    )

    with Live(layout, refresh_per_second=1, screen=True):
        while True:
            try:
                rows = get_latest_captures()
                gps_ok, node_count = get_node_status()

                layout["upper"].update(build_device_table(rows))
                layout["lower"].update(build_status_panel(gps_ok, node_count))

                time.sleep(REFRESH_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    main()
