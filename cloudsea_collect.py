#!/usr/bin/env python3
"""Immutable pre-event cloud-sea forecast snapshots, using Python stdlib only.

Does not modify the user-facing V4.13.1 scoring algorithm. Every model field and
its Open-Meteo metadata are preserved as originally returned.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TZ = dt.timezone(dt.timedelta(hours=8))
UTC = dt.timezone.utc
SITES = {
    "niucaoshan": {"label": "牛草山", "lat": 31.044687, "lon": 116.265979, "altitude_m": 1350},
    "taizijian": {"label": "太子尖", "lat": 30.1756, "lon": 118.8997, "altitude_m": 1557},
}
LEVELS = {
    "ECMWF": [1000, 925, 850, 700, 600, 500],
    "GFS": [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 725, 700, 675, 650, 625, 600, 575, 550, 525, 500],
}
BASE = {
    "composite_surface": ("https://api.open-meteo.com/v1/forecast", None),
    "ecmwf_surface": ("https://api.open-meteo.com/v1/ecmwf", "ecmwf_ifs025"),
    "gfs_surface": ("https://api.open-meteo.com/v1/gfs", "gfs_global"),
    "ecmwf_vertical": ("https://api.open-meteo.com/v1/ecmwf", "ecmwf_ifs025"),
    "gfs_vertical": ("https://api.open-meteo.com/v1/gfs", "gfs_global"),
}
SURFACE_VARS = "relative_humidity_2m,cloud_cover_low,cloud_cover,precipitation,wind_speed_10m,wind_direction_10m"
COMPOSITE_VARS = SURFACE_VARS + ",visibility"


def iso_utc():
    return dt.datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_url(site, name, start, end):
    endpoint, model = BASE[name]
    params = {"latitude": site["lat"], "longitude": site["lon"], "timezone": "Asia/Shanghai", "start_date": start, "end_date": end}
    if model:
        params["models"] = model
    if name.endswith("vertical"):
        levels = LEVELS["ECMWF" if name.startswith("ecmwf") else "GFS"]
        params["hourly"] = ",".join(f"{field}_{p}hPa" for p in levels for field in ("temperature", "relative_humidity", "cloud_cover", "geopotential_height"))
    else:
        params["hourly"] = COMPOSITE_VARS if name.startswith("composite") else SURFACE_VARS
    return endpoint + "?" + urlencode(params)


def fetch(url):
    last = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "CloudSeaArchive/1.0 (GitHub Actions)", "Accept": "application/json"})
            with urlopen(request, timeout=35) as res:
                response = json.load(res)
            if response.get("error"):
                raise RuntimeError(response.get("reason", "Open-Meteo API error"))
            if not isinstance(response.get("hourly", {}).get("time"), list):
                raise ValueError("missing hourly.time")
            return response, None
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None, last


def forecast_diagnostics(datasets, start, end, site):
    """Frozen *inputs*, not the web app's non-calibrated scores."""
    surface = datasets.get("composite_surface", {}).get("data")
    if not surface:
        return []
    hr = surface["hourly"]
    entries = []
    for day_offset in range((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1):
        day = (dt.date.fromisoformat(start) + dt.timedelta(days=day_offset)).isoformat()
        for label, hours in (("sunrise", (4, 5, 6, 7, 8)), ("sunset", (15, 16, 17, 18, 19))):
            ix = [i for i, stamp in enumerate(hr["time"]) if stamp.startswith(day + "T") and int(stamp[11:13]) in hours]
            def values(key):
                return [hr[key][i] for i in ix if key in hr and i < len(hr[key]) and isinstance(hr[key][i], (int, float))]
            def mean(key):
                v = values(key)
                return round(sum(v) / len(v), 2) if v else None
            entry = {"target_date": day, "window": label,
                     "hours_beijing": f"{min(hours):02d}:00–{max(hours):02d}:00",
                     "composite_low_cloud_mean_pct": mean("cloud_cover_low"),
                     "composite_humidity_mean_pct": mean("relative_humidity_2m"),
                     "composite_visibility_min_m": min(values("visibility"), default=None),
                     "composite_wind_mean_kmh": mean("wind_speed_10m"),
                     "composite_rain_sum_mm": round(sum(values("precipitation")), 3) if values("precipitation") else None,
                     "software_score": None,
                     "software_score_status": "not_computed; V4.13.1 algorithm not ported; never present as its score"}
            entries.append(entry)
    return entries


def run(output, start, end, sites, dry_run=False):
    output = Path(output)
    stamp = dt.datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    failures = []
    for name in sites:
        site = SITES[name]
        began = iso_utc()
        results = {}
        for endpoint in BASE:
            url = build_url(site, endpoint, start, end)
            if dry_run:
                print(name, endpoint, url[:145] + "…")
                continue
            data, err = fetch(url)
            results[endpoint] = {"requested_url": url, "received_at_utc": iso_utc(), "data": data, "error": err}
            if err:
                failures.append((name, endpoint, err))
            print(f"{name}: {endpoint}: {'OK' if data is not None else 'ERROR: '+str(err)}", flush=True)
            time.sleep(0.25)
        if dry_run:
            continue
        record = {"schema": "cloudsea-immutable-snapshot-v1", "collector_version": "collector-1.0.0",
                  "target_site": name, "site": site, "capture_started_utc": began,
                  "capture_finished_utc": iso_utc(), "capture_beijing": dt.datetime.now(TZ).isoformat(timespec="seconds"),
                  "forecast_target_dates": [start, end], "data_kind": "forecast_obtained_at_capture_time_not_observation",
                  "model_run_id": "not_exposed_by_forecast_API; use single-runs archive for run-level audit",
                  "web_app_algorithm_version": "V4.13.1 (not executed here)",
                  "web_app_scores": None,
                  "web_app_scores_note": "No claimed reproduction of V4.13.1 scores. Raw data is sufficient for separately versioned offline evaluation later.",
                  "datasets": results,
                  "diagnostics": forecast_diagnostics(results, start, end, site)}
        filename = f"{stamp}_{name}_{start}_to_{end}.json"
        folder = output / name / dt.datetime.now(TZ).strftime("%Y-%m")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        # Exclusive creation prevents silently replacing an existing capture.
        with path.open("x", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("Archived:", path, "bytes:", path.stat().st_size)
    if failures:
        print("Some sources unavailable; incomplete snapshots were still archived:", failures, file=sys.stderr)
        return 2
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="snapshots")
    parser.add_argument("--days", type=int, default=4, help="Include current Beijing date and next N-1 days")
    parser.add_argument("--sites", nargs="+", choices=list(SITES), default=list(SITES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.days <= 10:
        parser.error("--days must be between 1 and 10")
    today = dt.datetime.now(TZ).date()
    sys.exit(run(args.output, today.isoformat(), (today + dt.timedelta(days=args.days - 1)).isoformat(), args.sites, args.dry_run))


if __name__ == "__main__":
    main()
