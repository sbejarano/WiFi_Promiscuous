#!/usr/bin/env python3
"""
Trilateration / Multilateration of Wi-Fi AP locations from multi-probe captures.

Inputs:
  - SQLite DB: ~/wifi_promiscuous/data/captures.sqlite (default)
  - Table: wifi_captures (schema produced by aggregator.py)

Method (per BSSID):
  1) Collect all sightings with valid lat/lon (>=3 needed; with 2 → degenerate fit; 1 → skip).
  2) Convert (lat,lon,alt) of receiver positions to a local ENU frame
     centered at the median lat/lon/alt of that BSSID’s captures.
  3) Convert RSSI to an estimated range using a log-distance path loss model:
       d(rssi) = d0 * 10^((P0 - rssi) / (10 * n))
     where:
       - d0 is 1 m reference (fixed at 1 m),
       - P0 is RSSI at 1 m (default -40 dBm, configurable),
       - n is path-loss exponent (default 2.2 indoor-ish / 2.0–3.0; configurable),
     We also clamp ranges to [2 m, max_range_m] to avoid numerical pathologies.
  4) Weighted non-linear least squares on unknown AP position (x,y,z in ENU).
     Weights combine:
       - RSSI strength (stronger is better),
       - GPS HDOP/VDOP (lower is better),
       - Motion blur: higher ground speed increases measurement sigma.
  5) Confidence %:
       - Derived from residual RMS (meters) and the approximate covariance (J^T W J)^-1.
       - We transform the 2D (x,y) covariance to a circularized 95% radius (R95)
         and map it to [0..100] with: conf = max(0, 100 * exp(-R95 / conf_scale_m)).
         Default conf_scale_m = 100 m (configurable via CLI).

Output:
  - GeoJSON FeatureCollection written to:
      ~/wifi_promiscuous/geojson/trilateration_<UTC-YYYYmmdd_HHMMSS>.geojson
  - Feature properties per BSSID:
      {
        "bssid": "...",
        "ssid": "most_common_or_any",
        "num_obs": N,
        "mean_rssi": …,
        "time_start_utc": "...",
        "time_end_utc": "...",
        "method": "weighted_least_squares",
        "est_error_rms_m": …,
        "cov_R95_m": …,
        "confidence_pct": …,
        "notes": "fallback/fit info"
      }

CLI:
  trilaterate.py [--db PATH] [--min-obs N] [--since 'YYYY-mm-ddTHH:MM:SSZ' | --minutes N]
                 [--p0 -40] [--n 2.2] [--max-range 2000]
                 [--conf-scale 100] [--bssid XX:XX:... (repeatable)]
                 [--outfile PATH] [--quiet]

Examples:
  # Process last 30 minutes
  ./scripts/trilaterate.py --minutes 30

  # Specific BSSID only
  ./scripts/trilaterate.py --bssid 1C:8B:76:8F:89:DB --minutes 120

  # Use custom path loss model
  ./scripts/trilaterate.py --p0 -42 --n 2.0

Requires:
  numpy, scipy, pyproj, pandas, geojson  (already in requirements.txt)
"""

from __future__ import annotations
import argparse
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from pyproj import CRS, Transformer
import geojson

# ---------- Defaults ----------
DEF_DB = os.path.expanduser("~/wifi_promiscuous/data/captures.sqlite")
DEF_OUTDIR = os.path.expanduser("~/wifi_promiscuous/geojson")
MIN_OBS_DEFAULT = 3  # minimum observations per BSSID to attempt multilateration

# Path loss defaults
DEF_P0 = -40.0      # RSSI at 1m [dBm]
DEF_N = 2.2         # path loss exponent
DEF_MAX_RANGE = 2000.0  # meters; clamp to avoid blowups for weak RSSI

CONF_SCALE_M = 100.0    # meters scale for converting covariance radius to % confidence

# Motion weighting
BASE_SIGMA_M = 8.0      # base measurement sigma [m] for near-stationary good GPS & strong RSSI
SPEED_SIGMA_K = 1.0     # extra sigma per (m/s): sigma += k * speed
HDOP_MULT_K = 6.0       # sigma *= (1 + k*(hdop-0.5)) for hdop>0.5 (soft)
RSSI_CLAMP = (-95, -35) # clamp RSSI for weight scaling
ALT_WEIGHT = 0.5        # weight factor on z error vs x,y (makes z a bit looser)

@dataclass
class Obs:
    x: float; y: float; z: float
    rssi: float
    speed: Optional[float]
    track: Optional[float]
    hdop: Optional[float]
    vdop: Optional[float]
    ts: datetime

def now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def rssi_to_range(rssi: float, p0: float, n: float, d0: float = 1.0, max_range: float = DEF_MAX_RANGE) -> float:
    """Log-distance path loss model."""
    # d = d0 * 10^((P0 - RSSI)/(10n))
    d = d0 * (10.0 ** ((p0 - rssi) / (10.0 * n)))
    return float(min(max(d, 2.0), max_range))

def motion_weight_sigma(base_sigma: float, speed: Optional[float], hdop: Optional[float]) -> float:
    sigma = base_sigma
    if speed is not None:
        sigma += SPEED_SIGMA_K * max(0.0, float(speed))
    if (hdop is not None) and (hdop > 0.5):
        sigma *= (1.0 + HDOP_MULT_K * (hdop - 0.5))
    return sigma

def enu_transformer(lat0: float, lon0: float, alt0: float):
    """Return functions to go: (lat,lon,alt) <-> ENU (meters) around (lat0,lon0,alt0)."""
    wgs84 = CRS.from_epsg(4979)  # 3D WGS84
    # Local ENU as topocentric from origin
    enu = CRS.from_proj4(f"+proj=enu +lat_0={lat0} +lon_0={lon0} +h_0={alt0} +x_0=0 +y_0=0 +z_0=0 +datum=WGS84 +units=m +no_defs")
    fwd = Transformer.from_crs(wgs84, enu, always_xy=True)
    inv = Transformer.from_crs(enu, wgs84, always_xy=True)
    def to_enu(lat, lon, alt):
        x, y, z = fwd.transform(lon, lat, alt)
        return float(x), float(y), float(z)
    def to_llh(x, y, z):
        lon, lat, alt = inv.transform(x, y, z)
        return float(lat), float(lon), float(alt)
    return to_enu, to_llh

def robust_median(values: List[float]) -> float:
    arr = np.array(values, dtype=float)
    return float(np.median(arr))

def rms(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(a))))

def conf_from_cov_radius(R95_m: float, scale_m: float) -> float:
    """Map 95% radius to [0..100]% (smaller radius → higher confidence)."""
    if not np.isfinite(R95_m) or R95_m <= 0:
        return 100.0
    conf = 100.0 * math.exp(-(R95_m / max(1e-6, scale_m)))
    return max(0.0, min(100.0, conf))

def fit_bssid(enu_obs: List[Obs], p0: float, n_exp: float) -> Tuple[Optional[np.ndarray], Dict]:
    """
    Nonlinear weighted least squares for AP location (x,y,z).

    Residuals: (||AP - obs_i|| - d_i) / sigma_i, with z-residual downweighted (ALT_WEIGHT).
    """
    if len(enu_obs) < 3:
        return None, {"ok": False, "reason": "not_enough_observations"}

    # Initial guess: weighted centroid biased toward stronger RSSI (closer)
    w = []
    pts = []
    dists_guess = []
    for o in enu_obs:
        # Stronger RSSI → larger weight; clamp to reasonable bounds
        rs = float(np.clip(o.rssi, RSSI_CLAMP[0], RSSI_CLAMP[1]))
        w_i = (rs - RSSI_CLAMP[0]) / (RSSI_CLAMP[1] - RSSI_CLAMP[0] + 1e-9) + 0.1
        w.append(w_i)
        pts.append([o.x, o.y, o.z])
        dists_guess.append(rssi_to_range(o.rssi, p0, n_exp))
    w = np.array(w)
    pts = np.array(pts)
    x0 = np.average(pts, axis=0, weights=w)

    # Precompute per-obs sigmas and target ranges
    sigmas = []
    ranges = []
    for o in enu_obs:
        sigmas.append(motion_weight_sigma(BASE_SIGMA_M, o.speed, o.hdop))
        ranges.append(rssi_to_range(o.rssi, p0, n_exp))
    sigmas = np.array(sigmas, dtype=float)
    ranges = np.array(ranges, dtype=float)
    inv_sig = 1.0 / np.clip(sigmas, 1.0, 1e9)

    def residuals(x):
        # x: [Xap, Yap, Zap]
        dxyz = pts - x.reshape(1, 3)
        d = np.linalg.norm(dxyz, axis=1)
        # Separate z a bit so vertical error doesn't dominate
        # Implemented by slightly scaling z component distance when computing residual
        # (equivalent to changing geometry). Alternatively could scale residual by ALT_WEIGHT.
        # Here we apply residual scaling:
        # replace geometric distance by sqrt((dx^2+dy^2) + (ALT_WEIGHT*dz)^2)
        dx = dxyz[:, 0]; dy = dxyz[:, 1]; dz = dxyz[:, 2]
        d_adj = np.sqrt(dx*dx + dy*dy + (ALT_WEIGHT*dz)*(ALT_WEIGHT*dz))
        res = (d_adj - ranges) * inv_sig
        return res

    res = least_squares(residuals, x0, method="trf", loss="soft_l1", f_scale=1.0, max_nfev=200)
    ok = res.success and res.x.size == 3

    info = {
        "ok": bool(ok),
        "reason": res.message,
        "rms_residual_m": rms(res.fun / inv_sig) if res.fun.size else float("nan"),  # back out scaling
        "n_iter": res.nfev
    }

    if not ok:
        return None, info

    # Approximate covariance: (J^T J)^-1 scaled by residual variance
    try:
        J = res.jac
        # Convert residuals back to meters (undo inv_sig scaling)
        res_m = res.fun / inv_sig
        dof = max(1, len(res_m) - 3)
        sigma2 = float(np.dot(res_m, res_m) / dof)
        JTJ = J.T @ J
        cov = np.linalg.inv(JTJ) * sigma2
        info["covariance_3x3"] = cov
        # 2D covariance (x,y):
        cov2 = cov[:2, :2]
        # 2D 95% quantile radius for Gaussian ~ sqrt(5.991 * lambda_max)
        eigvals, _ = np.linalg.eig(cov2)
        lam_max = float(np.max(np.real(eigvals)))
        R95 = math.sqrt(max(0.0, 5.991 * max(lam_max, 0.0)))
        info["cov_R95_m"] = R95
    except Exception:
        info["covariance_3x3"] = None
        info["cov_R95_m"] = float("nan")

    return res.x, info

def load_data(conn: sqlite3.Connection,
              since_iso: Optional[str],
              minutes: Optional[int],
              include_bssids: List[str],
              min_obs: int) -> Dict[str, pd.DataFrame]:
    where = ["gps_lat IS NOT NULL", "gps_lon IS NOT NULL"]
    params = []
    if since_iso:
        where.append("ts_utc >= ?")
        params.append(since_iso)
    elif minutes:
        where.append("julianday(ts_utc) >= julianday('now', ?)")
        params.append(f"-{int(minutes)} minutes")

    if include_bssids:
        # Build an IN clause
        placeholders = ",".join(["?"] * len(include_bssids))
        where.append(f"bssid IN ({placeholders})")
        params.extend(include_bssids)

    sql = f"""
    SELECT ts_utc, node_id, channel, frequency_mhz, bssid, ssid, rssi_dbm,
           gps_lat, gps_lon, gps_alt_m, gps_speed_mps, gps_track_deg,
           gps_hdop, gps_vdop
    FROM wifi_captures
    WHERE {' AND '.join(where)}
    ORDER BY bssid, ts_utc
    """

    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return {}

    # Group by BSSID and keep only those with enough observations
    by_bssid: Dict[str, pd.DataFrame] = {}
    for bssid, g in df.groupby("bssid"):
        if len(g) >= max(1, min_obs):
            by_bssid[bssid] = g.reset_index(drop=True)
    return by_bssid

def pick_origin_llh(df: pd.DataFrame) -> Tuple[float, float, float]:
    lat0 = float(df["gps_lat"].median())
    lon0 = float(df["gps_lon"].median())
    # median altitude with fallback to 0 if missing
    alt0 = float(df["gps_alt_m"].dropna().median()) if df["gps_alt_m"].notna().any() else 0.0
    return lat0, lon0, alt0

def most_common_ssid(df: pd.DataFrame) -> str:
    clean = df["ssid"].fillna("").astype(str)
    # prefer non-empty; take the most frequent
    nonempty = clean[clean.str.len() > 0]
    if not nonempty.empty:
        return str(nonempty.mode().iat[0])
    return str(clean.mode().iat[0]) if not clean.empty else ""

def make_feature(lat: float, lon: float, alt: float, props: Dict) -> geojson.Feature:
    geom = geojson.Point((lon, lat, alt))
    return geojson.Feature(geometry=geom, properties=props)

def process_bssid(bssid: str,
                  df: pd.DataFrame,
                  p0: float, n_exp: float, conf_scale_m: float) -> Optional[geojson.Feature]:
    # Build ENU transform centered at the median location
    lat0, lon0, alt0 = pick_origin_llh(df)
    to_enu, to_llh = enu_transformer(lat0, lon0, alt0)

    # Fill observations
    obs: List[Obs] = []
    for _, row in df.iterrows():
        lat = float(row["gps_lat"])
        lon = float(row["gps_lon"])
        alt = float(row["gps_alt_m"]) if not pd.isna(row["gps_alt_m"]) else alt0
        x, y, z = to_enu(lat, lon, alt)
        rssi = float(row["rssi_dbm"])
        spd = None if pd.isna(row["gps_speed_mps"]) else float(row["gps_speed_mps"])
        trk = None if pd.isna(row["gps_track_deg"]) else float(row["gps_track_deg"])
        hdop = None if pd.isna(row["gps_hdop"]) else float(row["gps_hdop"])
        vdop = None if pd.isna(row["gps_vdop"]) else float(row["gps_vdop"])
        ts = datetime.fromisoformat(str(row["ts_utc"]).replace("Z", "+00:00"))
        obs.append(Obs(x, y, z, rssi, spd, trk, hdop, vdop, ts))

    if len(obs) < 3:
        # With <3 obs, produce a coarse line/point? For now, skip to avoid junk.
        return None

    # Fit
    x_est, info = fit_bssid(obs, p0=p0, n_exp=n_exp)
    if not info.get("ok", False) or x_est is None:
        return None

    # Convert back to lat/lon/alt
    lat_est, lon_est, alt_est = to_llh(float(x_est[0]), float(x_est[1]), float(x_est[2]))

    # Confidence from covariance radius
    R95 = float(info.get("cov_R95_m", float("nan")))
    confidence_pct = conf_from_cov_radius(R95, conf_scale_m)

    # Properties
    ssid = most_common_ssid(df)
    props = {
        "bssid": bssid,
        "ssid": ssid,
        "num_obs": int(len(df)),
        "mean_rssi": float(df["rssi_dbm"].mean()),
        "time_start_utc": str(df["ts_utc"].iloc[0]),
        "time_end_utc": str(df["ts_utc"].iloc[-1]),
        "method": "weighted_least_squares",
        "est_error_rms_m": float(info.get("rms_residual_m", float("nan"))),
        "cov_R95_m": R95,
        "confidence_pct": round(confidence_pct, 1),
        "notes": info.get("reason", "")
    }
    return make_feature(lat_est, lon_est, alt_est, props)

def main():
    ap = argparse.ArgumentParser(description="Trilaterate Wi-Fi AP locations to GeoJSON")
    ap.add_argument("--db", default=DEF_DB, help="Path to captures.sqlite")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--since", help="ISO start time (UTC), e.g. 2025-09-08T00:00:00Z")
    g.add_argument("--minutes", type=int, help="Look back N minutes from now")
    ap.add_argument("--min-obs", type=int, default=MIN_OBS_DEFAULT, help="Minimum observations per BSSID")
    ap.add_argument("--bssid", action="append", default=[], help="Filter to one or more BSSIDs (repeatable)")
    ap.add_argument("--p0", type=float, default=DEF_P0, help="RSSI at 1m (dBm)")
    ap.add_argument("--n", type=float, default=DEF_N, help="Path loss exponent")
    ap.add_argument("--max-range", type=float, default=DEF_MAX_RANGE, help="Clamp RSSI→range (m)")
    ap.add_argument("--conf-scale", type=float, default=CONF_SCALE_M, help="Confidence scale meters")
    ap.add_argument("--outfile", help="Write to this path (otherwise auto-named in geojson/)")
    ap.add_argument("--quiet", action="store_true", help="Reduce console output")
    args = ap.parse_args()

    # Sanity
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"[!] DB not found: {db_path}")

    # Optional: global max-range override in function (keep in model)
    global DEF_MAX_RANGE
    DEF_MAX_RANGE = float(args.max_range)

    # Build time filter
    since_iso = None
    if args.since:
        since_iso = args.since
    elif args.minutes:
        # We'll use SQL julianday('now','-N minutes') in the query
        pass

    # Load data
    conn = sqlite3.connect(str(db_path))
    try:
        bssid_groups = load_data(conn, since_iso=since_iso, minutes=args.minutes,
                                 include_bssids=[b.upper() for b in args.bssid],
                                 min_obs=args.min_obs)
    finally:
        conn.close()

    if not bssid_groups:
        print("[i] No data matching filters; nothing to trilaterate.")
        return 0

    # Build features
    features: List[geojson.Feature] = []
    processed = 0
    for bssid, df in bssid_groups.items():
        processed += 1
        if not args.quiet:
            print(f"[+] Fitting {bssid}  (N={len(df)})  RSSI mean={df['rssi_dbm'].mean():.1f} dBm")
        feat = process_bssid(bssid, df, p0=args.p0, n_exp=args.n, conf_scale_m=args.conf_scale)
        if feat is not None:
            features.append(feat)
        else:
            if not args.quiet:
                print(f"    -> skipped (insufficient geometry or failed fit)")

    if not features:
        print("[i] No successful fits; not writing GeoJSON.")
        return 0

    fc = geojson.FeatureCollection(features)

    # Output path
    if args.outfile:
        out_path = Path(args.outfile)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = Path(DEF_OUTDIR)
        ensure_dir(out_dir)
        out_path = out_dir / f"trilateration_{ts}.geojson"

    with open(out_path, "w", encoding="utf-8") as f:
        geojson.dump(fc, f, sort_keys=False)

    if not args.quiet:
        print(f"[✓] Wrote {len(features)} features → {out_path}")
    else:
        print(str(out_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
