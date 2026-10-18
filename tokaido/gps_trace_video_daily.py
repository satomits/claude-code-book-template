#!/usr/bin/env python3
"""
GoPro GPS軌跡動画ジェネレーター（1日分まとめ）

指定した日付のMP4ファイルを GPS開始時刻の昇順で処理し、
1本の動画に結合する。

- 距離表示: ファイル間で積算（ファイルをまたいでも累計距離が継続）
- グラフ:   各ファイル単位で表示（ファイルが変わるとリセット）
- 地図:     全ファイルの全軌跡を下書き表示 + 現在位置

Usage:
    python3 gps_trace_video_daily.py <mp4_dir> --date 2024-03-01 [--output out.mp4] [--fps 10]
    python3 gps_trace_video_daily.py <mp4_dir> --date 2024-03-01 --health-export ~/health_export

    <mp4_dir>        : MP4ファイルが入ったディレクトリ
    --date           : 対象日付 (YYYY-MM-DD)。省略時はディレクトリ内の全MP4を処理。
    --health-export  : HealthKitエクスポートディレクトリ (心拍数+GPS融合)
"""

import argparse
import functools
import json
import math
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests
from staticmap import StaticMap, Line, CircleMarker

JST = timezone(timedelta(hours=9))

# ── 出力サイズ ──────────────────────────────────
OUT_W   = 1920
OUT_H   = 1080
TOP_H   = OUT_H // 2
STATS_H = 60
GRAPH_H = OUT_H - TOP_H - STATS_H
HALF_W  = OUT_W // 2

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_ZOOM = 14

DIST_COLOR_STOPS = [
    (10.0,         "#2979FF"),
    (20.0,         "#00C853"),
    (30.0,         "#FFD600"),
    (float("inf"), "#FF1744"),
]

import matplotlib.font_manager as fm

_JP_FONTS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
    "/Library/Fonts/Arial Unicode MS.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_PATH = next((f for f in _JP_FONTS if os.path.exists(f)), None)
if FONT_PATH is None:
    for _f in fm.findSystemFonts():
        try:
            name = fm.FontProperties(fname=_f).get_name()
            if any(k in name for k in ["Hiragino", "IPA", "Noto", "Gothic", "Meiryo", "YuGothic"]):
                FONT_PATH = _f
                break
        except Exception:
            continue

if FONT_PATH and os.path.exists(FONT_PATH):
    try:
        matplotlib.rcParams["font.family"] = fm.FontProperties(fname=FONT_PATH).get_name()
    except Exception:
        pass


def run(cmd, check=True, capture=True):
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


# ── GPS データ抽出・処理 ──────────────────────────

def parse_dms(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    import re
    m = re.match(r"(\d+)\s*deg\s*(\d+)'\s*([\d.]+)\"\s*([NSEW]?)", s)
    if m:
        deg, mn, sec, hem = m.groups()
        val = float(deg) + float(mn) / 60 + float(sec) / 3600
        if hem in ("S", "W"):
            val = -val
        return val
    return None


def parse_gps_datetime(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip().rstrip("Z")
    for fmt in (
        "%Y:%m:%d %H:%M:%S.%f",
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc).astimezone(JST)
        except ValueError:
            continue
    return None


def _get_gpmf_packet_times(video_path: str) -> list[float]:
    """ffprobe でGPMFストリームの各パケットの動画内タイムスタンプを取得する"""
    # gpmd (GoPro Metadata) ストリームを探す
    probe = run([
        "ffprobe", "-v", "quiet", "-show_streams", "-of", "json", video_path,
    ], check=False)
    gpmd_idx = None
    try:
        for s in json.loads(probe)["streams"]:
            if s.get("codec_tag_string") == "gpmd":
                gpmd_idx = s["index"]
                break
    except Exception:
        pass
    if gpmd_idx is None:
        return []

    out = run([
        "ffprobe", "-v", "quiet",
        "-select_streams", str(gpmd_idx),
        "-show_entries", "packet=pts_time",
        "-of", "csv=p=0", video_path,
    ], check=False)
    times = []
    for line in out.strip().splitlines():
        try:
            times.append(float(line.strip()))
        except ValueError:
            continue
    return times


def extract_gps_gpmf(video_path: str) -> list[dict]:
    """GPS抽出: exiftoolの行順序 = GPMFパケット順序 = 動画フレーム順序"""
    print(f"  exiftool でGPS抽出: {Path(video_path).name}")
    template = "$GPSDateTime|$GPSLatitude|$GPSLongitude|$GPSAltitude|$GPSSpeed3D"
    out = run(["exiftool", "-ee3", "-p", template, video_path], check=False)

    # ffprobe でGPMFパケットの動画内タイムスタンプを取得
    packet_times = _get_gpmf_packet_times(video_path)

    lines = out.strip().splitlines()
    points = []
    for idx, line in enumerate(lines):
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            lat = parse_dms(parts[1].strip())
            lon = parse_dms(parts[2].strip())
            alt = float(parts[3].strip().split()[0]) if len(parts) > 3 and parts[3].strip() else 0.0
            dt  = parse_gps_datetime(parts[0].strip())
            if lat is not None and lon is not None and dt is not None:
                # 動画内タイムスタンプ: パケットタイムがあればそれを使用
                video_ts = packet_times[idx] if idx < len(packet_times) else None
                points.append({"time": dt, "lat": lat, "lon": lon,
                                "alt": alt, "speed_kmh": 0.0,
                                "video_ts": video_ts})
        except Exception:
            continue

    print(f"    → {len(points)} 点 (パケットタイム: {'あり' if packet_times else 'なし'})")
    return points


def average_gps_by_second(points: list[dict]) -> list[dict]:
    """GPS時刻ベースで秒単位に集約。video_ts は各バケットの中央値を保持。"""
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for p in points:
        t = p["time"].replace(microsecond=0)
        buckets[t].append(p)
    result = []
    for t in sorted(buckets.keys()):
        ps = buckets[t]
        # video_ts はバケット内の中央値を使用（動画フレーム位置を保持）
        vts_list = [p["video_ts"] for p in ps if p.get("video_ts") is not None]
        video_ts = sorted(vts_list)[len(vts_list) // 2] if vts_list else None
        result.append({
            "time": t,
            "lat":  sum(p["lat"] for p in ps) / len(ps),
            "lon":  sum(p["lon"] for p in ps) / len(ps),
            "alt":  sum(p["alt"] for p in ps) / len(ps),
            "speed_kmh": 0.0,
            "video_ts": video_ts,
        })
    return result


def haversine_m(p1: dict, p2: dict) -> float:
    R = 6371000.0
    lat1, lon1 = math.radians(p1["lat"]), math.radians(p1["lon"])
    lat2, lon2 = math.radians(p2["lat"]), math.radians(p2["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(max(0.0, a)))


def mark_gps_startup_unstable(points: list[dict], max_speed_kmh: float = 50.0,
                              stability_window: int = 3) -> list[dict]:
    """GPS起動直後の連続した異常値のみを不安定マークする（削除しない）。

    先頭から連続して異常（速度超過 or ダミー座標）な区間だけをマークする。
    途中の一時的な異常値（トンネル出口等）はここでは処理しない
    （clean_gps_points の個別処理に任せる）。
    """
    if len(points) < 3:
        return points

    # 先頭から連続して不安定な区間を探す
    stable_start = 0
    for i in range(len(points)):
        # lat=0, lon=0 のダミー座標
        if abs(points[i]["lat"]) < 0.01 and abs(points[i]["lon"]) < 0.01:
            stable_start = i + 1
            continue
        # 速度チェック（前の点との比較）
        if i > 0 and stable_start == i:
            # 先頭からの連続不安定区間の延長チェック
            prev = points[i-1] if i-1 >= stable_start else None
            if prev is None and i >= 1:
                prev = points[i-1]
            dist_m = haversine_m(points[i-1], points[i])
            dt = (points[i]["time"] - points[i-1]["time"]).total_seconds()
            speed = (dist_m / dt * 3.6) if dt > 0 else 0.0
            if speed > max_speed_kmh:
                stable_start = i + 1
                continue
        # 安定区間が stability_window 点続いたら確定
        if i >= stable_start + stability_window:
            break
        # まだ stability_window に達していない: 次の点との速度もチェック
        if i + 1 < len(points) and i >= stable_start:
            dist_m = haversine_m(points[i], points[i+1])
            dt = (points[i+1]["time"] - points[i]["time"]).total_seconds()
            speed = (dist_m / dt * 3.6) if dt > 0 else 0.0
            if speed > max_speed_kmh:
                stable_start = i + 2

    if stable_start == 0:
        return points
    if stable_start >= len(points):
        return points

    # 最初の安定点の座標で不安定区間を埋める
    anchor = points[stable_start]
    n_marked = stable_start
    print(f"    → GPS起動不安定: 先頭 {n_marked} 点を不安定マーク（動画フレームは保持）")

    result = []
    for i, p in enumerate(points):
        if i < stable_start:
            result.append({
                **p,
                "lat": anchor["lat"],
                "lon": anchor["lon"],
                "alt": anchor["alt"],
                "gps_unstable": True,
            })
        else:
            result.append(p)
    return result


def clean_gps_points(points: list[dict], max_speed_kmh: float = 50.0) -> list[dict]:
    if len(points) < 3:
        return [{**p, "gps_unstable": False} for p in points]

    # 起動直後の不安定データをマーク（削除しない）
    points = mark_gps_startup_unstable(points, max_speed_kmh)

    valid = [True] * len(points)
    for i in range(1, len(points)):
        dist_m = haversine_m(points[i-1], points[i])
        dt     = (points[i]["time"] - points[i-1]["time"]).total_seconds()
        if dt > 0 and (dist_m / dt * 3.6) > max_speed_kmh:
            valid[i] = False

    n_bad = valid.count(False)
    if n_bad:
        print(f"    → GPS不安定 {n_bad} 点を最後の正常位置で固定")

    # 異常値は直前の正常点の座標を保持（補間しない）
    cleaned = [dict(p) for p in points]
    last_good_i = 0  # 最初の点は正常とみなす
    for i in range(1, len(points)):
        if valid[i]:
            last_good_i = i
        else:
            for key in ("lat", "lon", "alt"):
                cleaned[i][key] = points[last_good_i][key]

    # 速度計算は正常点間のみで行い、不安定点は速度0
    raw_speeds = [0.0]
    for i in range(1, len(cleaned)):
        if not valid[i] or not valid[i-1]:
            raw_speeds.append(0.0)
        else:
            dist_m = haversine_m(cleaned[i-1], cleaned[i])
            dt     = (cleaned[i]["time"] - cleaned[i-1]["time"]).total_seconds()
            raw_speeds.append((dist_m / dt * 3.6) if dt > 0 else 0.0)

    W = 5
    smoothed: list[float] = []
    for i in range(len(raw_speeds)):
        win = raw_speeds[max(0, i - W // 2) : i + W // 2 + 1]
        smoothed.append(sorted(win)[len(win) // 2])

    return [{**p, "speed_kmh": smoothed[i], "gps_unstable": not valid[i]}
            for i, p in enumerate(cleaned)]


def calc_distance(points: list[dict]) -> list[float]:
    R = 6371.0
    dists = [0.0]
    for i in range(1, len(points)):
        # 不安定な点では距離を加算しない
        if points[i].get("gps_unstable") or points[i-1].get("gps_unstable"):
            dists.append(dists[-1])
            continue
        lat1 = math.radians(points[i-1]["lat"])
        lon1 = math.radians(points[i-1]["lon"])
        lat2 = math.radians(points[i]["lat"])
        lon2 = math.radians(points[i]["lon"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        dists.append(dists[-1] + 2 * R * math.asin(math.sqrt(max(0.0, a))))
    return dists


def dist_to_color(dist_km: float) -> str:
    for threshold, color in DIST_COLOR_STOPS:
        if dist_km < threshold:
            return color
    return DIST_COLOR_STOPS[-1][1]


@functools.lru_cache(maxsize=512)
def _fetch_location_name(lat_r: float, lon_r: float) -> str:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat_r, "lon": lon_r, "format": "json", "accept-language": "ja"},
            headers={"User-Agent": "gps_trace_video/1.0"},
            timeout=5,
        )
        addr = resp.json().get("address", {})
        prefecture   = addr.get("state", "")
        municipality = (addr.get("city") or addr.get("town") or
                        addr.get("village") or addr.get("county") or "")
        if prefecture and municipality:
            return f"{prefecture} {municipality}"
        return prefecture or municipality
    except Exception:
        return ""


def get_location_name(lat: float, lon: float) -> str:
    return _fetch_location_name(round(lat, 2), round(lon, 2))


# ── HealthKit / GPX パース ──────────────────────────

def parse_heartrate_from_healthkit(
    export_xml_path: str, start_time: datetime, end_time: datetime,
) -> list[dict]:
    """export.xml から指定時刻範囲の心拍数レコードを抽出する"""
    hr_type = "HKQuantityTypeIdentifierHeartRate"
    results = []
    for event, elem in ET.iterparse(export_xml_path, events=("end",)):
        if elem.tag != "Record":
            elem.clear()
            continue
        if elem.get("type") != hr_type:
            elem.clear()
            continue
        date_str = elem.get("startDate", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            elem.clear()
            continue
        if start_time <= dt <= end_time:
            try:
                bpm = float(elem.get("value", "0"))
                results.append({"time": dt.astimezone(JST), "bpm": bpm})
            except ValueError:
                pass
        elem.clear()
    results.sort(key=lambda r: r["time"])
    return results


def parse_gpx_route(gpx_path: str) -> list[dict]:
    """ワークアウトGPXファイルからGPSポイントを抽出する"""
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    # GPX名前空間を検出
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    results = []
    for trkpt in root.iter(f"{ns}trkpt"):
        lat = float(trkpt.get("lat", "0"))
        lon = float(trkpt.get("lon", "0"))

        ele_elem = trkpt.find(f"{ns}ele")
        alt = float(ele_elem.text) if ele_elem is not None and ele_elem.text else 0.0

        time_elem = trkpt.find(f"{ns}time")
        if time_elem is None or not time_elem.text:
            continue
        dt = parse_gps_datetime(time_elem.text)
        if dt is None:
            continue

        # extensions から hAcc を取得
        h_acc = 10.0  # デフォルト
        extensions = trkpt.find(f"{ns}extensions")
        if extensions is not None:
            for child in extensions:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "hAcc" and child.text:
                    try:
                        h_acc = float(child.text)
                    except ValueError:
                        pass

        results.append({
            "time": dt, "lat": lat, "lon": lon, "alt": alt, "h_acc": h_acc,
        })
    results.sort(key=lambda r: r["time"])
    return results


def find_matching_workout_gpx(
    export_dir: str, start_time: datetime, end_time: datetime,
) -> list[str]:
    """export.xml のWorkout要素から時刻が重なるワークアウトのGPXパスを返す"""
    export_xml = os.path.join(export_dir, "export.xml")
    if not os.path.exists(export_xml):
        return []

    gpx_paths = []
    for event, elem in ET.iterparse(export_xml, events=("end",)):
        if elem.tag != "Workout":
            if elem.tag not in ("Record", "Workout"):
                elem.clear()
            continue

        w_start_str = elem.get("startDate", "")
        w_end_str = elem.get("endDate", "")
        try:
            w_start = datetime.strptime(w_start_str, "%Y-%m-%d %H:%M:%S %z")
            w_end = datetime.strptime(w_end_str, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            elem.clear()
            continue

        # 時刻の重なり判定
        if w_start <= end_time and w_end >= start_time:
            for ref in elem.iter("FileReference"):
                path = ref.get("path", "")
                if path.endswith(".gpx"):
                    # export.xml からの相対パスで workout-routes/ 内のファイルを探す
                    gpx_full = os.path.join(export_dir, path)
                    if os.path.exists(gpx_full):
                        gpx_paths.append(gpx_full)
                    else:
                        # パスが "workout-routes/route_xxx.gpx" 形式の場合
                        basename = os.path.basename(path)
                        alt_path = os.path.join(export_dir, "workout-routes", basename)
                        if os.path.exists(alt_path):
                            gpx_paths.append(alt_path)
        elem.clear()
    return gpx_paths


def find_gpx_by_date(export_dir: str, date_str: str) -> list[str]:
    """workout-routes/ ディレクトリからファイル名に日付を含むGPXを直接検索する。

    find_matching_workout_gpx のフォールバック用。
    ファイル名パターン例: route_2025-06-17_6.37am.gpx
    """
    routes_dir = os.path.join(export_dir, "workout-routes")
    if not os.path.isdir(routes_dir):
        return []
    return sorted(
        os.path.join(routes_dir, f)
        for f in os.listdir(routes_dir)
        if f.endswith(".gpx") and date_str in f and not f.startswith("._")
    )


# ── GPS融合 ──────────────────────────────────────

def fuse_gps_points(
    gopro_points: list[dict], iphone_points: list[dict],
    gopro_accuracy: float = 10.0,
    divergence_threshold_m: float = 100.0,
) -> list[dict]:
    """GoProとiPhoneのGPSデータを融合する。

    - GoProとiPhoneの位置が大きくずれている場合(>100m): iPhoneを採用(GoPro異常値)
    - iPhoneの精度(hAcc)がGoProより良い場合: iPhoneの値をそのまま採用
    - GoProの精度が良い場合: GoProの値を採用
    - 同程度の場合: 加重平均で融合
    """
    if not iphone_points:
        return [{**p, "source": "gopro"} for p in gopro_points]

    # iPhoneポイントを秒単位の辞書に変換
    iphone_by_sec: dict[datetime, dict] = {}
    for ip in iphone_points:
        key = ip["time"].replace(microsecond=0)
        iphone_by_sec[key] = ip

    fused = []
    n_iphone = 0
    n_gopro_only = 0
    n_blended = 0
    n_diverged = 0
    for gp in gopro_points:
        key = gp["time"].replace(microsecond=0)
        ip = iphone_by_sec.get(key)
        if ip is None:
            fused.append({**gp, "source": "gopro"})
            n_gopro_only += 1
            continue

        # GoProとiPhoneの距離差を計算
        dist_diff = haversine_m(
            {"lat": gp["lat"], "lon": gp["lon"]},
            {"lat": ip["lat"], "lon": ip["lon"]},
        )

        iphone_acc = ip["h_acc"] if ip["h_acc"] > 0 else gopro_accuracy

        # GoProが大きくずれている場合(>100m): iPhoneを強制採用
        if dist_diff > divergence_threshold_m:
            fused.append({
                "time": gp["time"],
                "lat": ip["lat"],
                "lon": ip["lon"],
                "alt": ip["alt"],
                "speed_kmh": gp.get("speed_kmh", 0.0),
                "video_ts": gp.get("video_ts"),
                "source": "iphone",
                "gps_unstable": False,
            })
            n_diverged += 1
        # iPhoneの精度がGoProより明確に良い場合はiPhoneを採用
        elif iphone_acc < gopro_accuracy * 0.5:
            fused.append({
                "time": gp["time"],
                "lat": ip["lat"],
                "lon": ip["lon"],
                "alt": ip["alt"],
                "speed_kmh": gp.get("speed_kmh", 0.0),
                "video_ts": gp.get("video_ts"),
                "source": "iphone",
            })
            n_iphone += 1
        # GoProの精度がiPhoneより明確に良い場合はGoProを採用
        elif gopro_accuracy < iphone_acc * 0.5:
            fused.append({**gp, "source": "gopro"})
            n_gopro_only += 1
        # 同程度の場合は加重平均
        else:
            w_gopro = 1.0 / (gopro_accuracy ** 2)
            w_iphone = 1.0 / (iphone_acc ** 2)
            w_total = w_gopro + w_iphone
            fused.append({
                "time": gp["time"],
                "lat": (gp["lat"] * w_gopro + ip["lat"] * w_iphone) / w_total,
                "lon": (gp["lon"] * w_gopro + ip["lon"] * w_iphone) / w_total,
                "alt": (gp["alt"] * w_gopro + ip["alt"] * w_iphone) / w_total,
                "speed_kmh": gp.get("speed_kmh", 0.0),
                "video_ts": gp.get("video_ts"),
                "source": "fused",
            })
            n_blended += 1

    print(f"      GPS融合: iPhone採用={n_iphone}  GoPro採用={n_gopro_only}  "
          f"加重平均={n_blended}  GoPro異常値→iPhone={n_diverged}")
    return fused


# ── レンダリング ──────────────────────────────────

def extract_video_frame(video_path: str, timestamp_sec: float, out_path: str):
    run([
        "ffmpeg", "-y", "-ss", str(timestamp_sec),
        "-i", video_path,
        "-vframes", "1", "-q:v", "2", out_path,
    ], capture=True, check=False)


def render_map(
    all_segments: list[dict],   # 全セグメント情報（全軌跡の下書きに使用）
    seg_idx: int,               # 現在のセグメントインデックス
    current_local_idx: int,     # 現在セグメント内のポイントインデックス
    global_dist_km: float,      # 累積距離（色分けに使用）
    size: tuple[int, int],
) -> Image.Image:
    seg     = all_segments[seg_idx]
    points  = seg["points"]
    lat     = points[current_local_idx]["lat"]
    lon     = points[current_local_idx]["lon"]

    m = StaticMap(size[0], size[1], url_template=TILE_URL)

    # 全ファイルの全ルートをグレーで下書き（安定点のみ）
    for s in all_segments:
        stable = [p for p in s["points"] if not p.get("gps_unstable")]
        if len(stable) > 1:
            coords = [(p["lon"], p["lat"]) for p in stable]
            m.add_line(Line(coords, "#444444", 2))

    # 走行済み軌跡を距離グラデーションで描画
    # セグメントをまたいで「グローバル距離」で色分けする
    for si, s in enumerate(all_segments):
        pts   = s["points"]
        dists = s["local_dists"]   # セグメント内の累積距離
        offset = s["dist_offset"]  # このセグメント開始時点のグローバル距離

        # このセグメントの描画終点
        if si < seg_idx:
            end_idx = len(pts)   # 完了済みセグメント: 全点
        elif si == seg_idx:
            end_idx = current_local_idx + 1   # 現在のセグメント: 現在点まで
        else:
            break   # 未来のセグメントは描画しない

        if end_idx < 2:
            continue

        # 不安定な点をスキップして軌跡線を描画
        seg_coords = []
        seg_color  = None

        for i in range(end_idx):
            if pts[i].get("gps_unstable"):
                # 不安定点で線を切る
                if len(seg_coords) >= 2:
                    m.add_line(Line(seg_coords, seg_color, 5))
                seg_coords = []
                seg_color = None
                continue

            color = dist_to_color(offset + dists[i])
            coord = (pts[i]["lon"], pts[i]["lat"])
            if seg_color is None:
                seg_coords = [coord]
                seg_color = color
            elif color == seg_color:
                seg_coords.append(coord)
            else:
                if len(seg_coords) >= 2:
                    m.add_line(Line(seg_coords, seg_color, 5))
                seg_coords = [seg_coords[-1], coord]
                seg_color  = color
        if len(seg_coords) >= 2:
            m.add_line(Line(seg_coords, seg_color, 5))

    cur_color = dist_to_color(global_dist_km)
    m.add_marker(CircleMarker((lon, lat), "#FFFFFF", 16))
    m.add_marker(CircleMarker((lon, lat), cur_color,  11))

    try:
        img = m.render(zoom=MAP_ZOOM, center=[lon, lat])
    except Exception as e:
        print(f"  ⚠ 地図レンダリングエラー: {e}")
        img = Image.new("RGB", size, "#c8e6c9")

    img = img.convert("RGB").resize(size, Image.LANCZOS)

    location = get_location_name(lat, lon)
    if location:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(FONT_PATH, 28) if FONT_PATH else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        pad = 10
        bb  = font.getbbox(location)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        bx0, by0 = pad, size[1] - th - pad * 2 - 4
        bx1, by1 = bx0 + tw + pad * 2, size[1] - pad
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rounded_rectangle([bx0, by0, bx1, by1], radius=6, fill=(0, 0, 0, 160))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((bx0 + pad, by0 + 4), location, font=font, fill="#FFFFFF")

    return img


def render_stats_bar(
    point: dict,
    global_distance_km: float,   # 積算距離
    size: tuple[int, int],
    heart_rate_bpm: float | None = None,
) -> Image.Image:
    img  = Image.new("RGB", size, "#0D1117")
    draw = ImageDraw.Draw(img)
    try:
        font_val   = ImageFont.truetype(FONT_PATH, 30) if FONT_PATH else ImageFont.load_default()
        font_label = ImageFont.truetype(FONT_PATH, 20) if FONT_PATH else ImageFont.load_default()
    except Exception:
        font_val = font_label = ImageFont.load_default()

    w, h = size
    dt = point["time"]
    items = [
        (None,   dt.strftime("%Y-%m-%d  %H:%M:%S JST"), "#FFFFFF"),
        ("速度",  f"{point['speed_kmh']:.1f} km/h",     "#FF9100"),
        ("高度",  f"{point['alt']:.0f} m",               "#29B6F6"),
        ("距離",  f"{global_distance_km:.2f} km",        "#69F0AE"),  # 積算距離
    ]
    if heart_rate_bpm is not None:
        items.append(("❤ 心拍", f"{heart_rate_bpm:.0f} bpm", "#FF4081"))
    col_w    = w // len(items)
    y_center = h // 2

    for idx, (label, value, color) in enumerate(items):
        cx = col_w * idx + col_w // 2
        if label is None:
            bb = font_val.getbbox(value)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            draw.text((cx - tw // 2, y_center - th // 2), value, font=font_val, fill=color)
        else:
            lb = font_label.getbbox(label)
            lw, lh = lb[2] - lb[0], lb[3] - lb[1]
            vb = font_val.getbbox(value)
            vw, vh = vb[2] - vb[0], vb[3] - vb[1]
            total_h = lh + 4 + vh
            y0 = y_center - total_h // 2
            draw.text((cx - lw // 2, y0),          label, font=font_label, fill="#9E9E9E")
            draw.text((cx - vw // 2, y0 + lh + 4), value, font=font_val,   fill=color)

    for idx in range(1, len(items)):
        x = col_w * idx
        draw.line([(x, 6), (x, h - 6)], fill="#30363D", width=1)

    return img


def _interpolate_hr_for_dists(
    seg_points: list[dict], seg_local_dists: list[float],
    hr_data: list[dict],
) -> list[float | None]:
    """セグメント内の各ポイントに対応する心拍数を補間で求める"""
    if not hr_data:
        return [None] * len(seg_points)

    result: list[float | None] = []
    hr_idx = 0
    for i, pt in enumerate(seg_points):
        t = pt["time"]
        # hr_data 内で最も近い時刻を探す
        while hr_idx < len(hr_data) - 1 and hr_data[hr_idx + 1]["time"] <= t:
            hr_idx += 1

        # 最近傍が30秒以内ならその値を使う
        best = hr_data[hr_idx]
        diff = abs((best["time"] - t).total_seconds())
        if hr_idx + 1 < len(hr_data):
            diff2 = abs((hr_data[hr_idx + 1]["time"] - t).total_seconds())
            if diff2 < diff:
                best = hr_data[hr_idx + 1]
                diff = diff2
        result.append(best["bpm"] if diff <= 30 else None)
    return result


# 心拍ゾーン定義 (Zone1-5)
HR_ZONES = [
    (1, 100, "#4FC3F7"),   # Zone1: ~100 bpm (軽い)
    (2, 120, "#66BB6A"),   # Zone2: 100-120 bpm (脂肪燃焼)
    (3, 140, "#FFD54F"),   # Zone3: 120-140 bpm (有酸素)
    (4, 160, "#FF8A65"),   # Zone4: 140-160 bpm (閾値)
    (5, 220, "#EF5350"),   # Zone5: 160+ bpm (最大)
]


def render_combined_graph(
    seg_points: list[dict],     # 現在セグメントのみのポイント
    seg_local_dists: list[float],  # 現在セグメントのローカル距離
    current_idx: int,
    size: tuple[int, int],
    hr_values: list[float | None] | None = None,
) -> Image.Image:
    """グラフは現在ファイル単位で表示（距離軸はセグメント内の相対距離）"""
    has_hr = hr_values and any(v is not None for v in hr_values)

    fig, ax1 = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    fig.patch.set_facecolor("#0D1117")
    ax1.set_facecolor("#161B22")

    alts   = [p["alt"]       for p in seg_points]
    speeds = [p["speed_kmh"] for p in seg_points]
    dists  = seg_local_dists
    ci     = current_idx

    ax2 = ax1.twinx()

    ax1.fill_between(dists[:ci+1], alts[:ci+1], alpha=0.2, color="#29B6F6")
    ax1.plot(dists, alts,               color="#2a3a4a", linewidth=1.0, zorder=1)
    ax1.plot(dists[:ci+1], alts[:ci+1], color="#29B6F6", linewidth=2.0, zorder=2)
    ax1.set_ylabel("高度 (m)", color="#29B6F6", fontsize=10)
    ax1.tick_params(axis="y", colors="#29B6F6")

    ax2.plot(dists, speeds,               color="#2a3a4a", linewidth=1.0, zorder=1)
    ax2.plot(dists[:ci+1], speeds[:ci+1], color="#FF9100", linewidth=2.0, zorder=2)
    ax2.set_ylabel("速度 (km/h)", color="#FF9100", fontsize=10)
    ax2.tick_params(axis="y", colors="#FF9100")

    # 心拍数の第3軸
    if has_hr:
        ax3 = ax1.twinx()
        ax3.spines["right"].set_position(("axes", 1.08))

        # 心拍ゾーン帯を背景表示
        zone_bottom = 0
        for zone_num, zone_top, zone_color in HR_ZONES:
            ax3.axhspan(zone_bottom, zone_top, alpha=0.06, color=zone_color, zorder=0)
            zone_bottom = zone_top

        # 心拍数の有効値だけをプロット
        hr_dists_all = [dists[i] for i in range(len(hr_values)) if hr_values[i] is not None]
        hr_vals_all = [hr_values[i] for i in range(len(hr_values)) if hr_values[i] is not None]
        hr_dists_cur = [dists[i] for i in range(ci + 1) if hr_values[i] is not None]
        hr_vals_cur = [hr_values[i] for i in range(ci + 1) if hr_values[i] is not None]

        if hr_dists_all:
            ax3.plot(hr_dists_all, hr_vals_all, color="#3a2a3a", linewidth=1.0, zorder=1)
        if hr_dists_cur:
            ax3.plot(hr_dists_cur, hr_vals_cur, color="#FF4081", linewidth=2.0, zorder=2)
            ax3.scatter([hr_dists_cur[-1]], [hr_vals_cur[-1]], color="#FF4081", zorder=5, s=60,
                        edgecolors="#FFFFFF", linewidths=1.2)

        ax3.set_ylabel("心拍数 (bpm)", color="#FF4081", fontsize=10)
        ax3.tick_params(axis="y", colors="#FF4081")
        ax3.set_ylim(40, 200)
        for spine in ax3.spines.values():
            spine.set_edgecolor("#30363D")

    ax1.axvline(x=dists[ci], color="#FF1744", linewidth=1.5, linestyle="--", alpha=0.8, zorder=3)
    ax1.scatter([dists[ci]], [alts[ci]],   color="#29B6F6", zorder=5, s=60,
                edgecolors="#FFFFFF", linewidths=1.2)
    ax2.scatter([dists[ci]], [speeds[ci]], color="#FF9100", zorder=5, s=60,
                edgecolors="#FFFFFF", linewidths=1.2)

    ax1.set_xlabel("距離 (km)", color="#9E9E9E", fontsize=10)
    ax1.tick_params(axis="x", colors="#9E9E9E")
    for spine in list(ax1.spines.values()) + list(ax2.spines.values()):
        spine.set_edgecolor("#30363D")
    ax1.grid(True, color="#30363D", linewidth=0.5)

    legend_lines = [
        plt.Line2D([0], [0], color="#29B6F6", linewidth=2, label="高度"),
        plt.Line2D([0], [0], color="#FF9100", linewidth=2, label="速度"),
    ]
    if has_hr:
        legend_lines.append(plt.Line2D([0], [0], color="#FF4081", linewidth=2, label="心拍数"))
    ax1.legend(handles=legend_lines, loc="upper left",
               facecolor="#161B22", edgecolor="#30363D",
               labelcolor="#FFFFFF", fontsize=9)

    plt.tight_layout(pad=0.5)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=".") as tmp:
        plt.savefig(tmp.name, facecolor=fig.get_facecolor())
        plt.close(fig)
        img = Image.open(tmp.name).convert("RGB").resize(size, Image.LANCZOS)
        os.unlink(tmp.name)
    return img


def compose_frame(
    video_frame: Image.Image | None,
    map_img: Image.Image,
    stats_img: Image.Image,
    graph_img: Image.Image,
) -> Image.Image:
    canvas = Image.new("RGB", (OUT_W, OUT_H), "#0D1117")
    vf = (video_frame.resize((HALF_W, TOP_H), Image.LANCZOS)
          if video_frame else Image.new("RGB", (HALF_W, TOP_H), "#1A1A2E"))
    canvas.paste(vf,       (0,      0))
    canvas.paste(map_img.resize((HALF_W, TOP_H), Image.LANCZOS), (HALF_W, 0))
    canvas.paste(stats_img.resize((OUT_W, STATS_H), Image.LANCZOS), (0, TOP_H))
    canvas.paste(graph_img.resize((OUT_W, GRAPH_H), Image.LANCZOS), (0, TOP_H + STATS_H))
    return canvas


def get_video_duration(video_path: str) -> float:
    out = run([
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", video_path,
    ], check=False)
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def get_video_start_time(video_path: str, duration: float) -> datetime | None:
    """動画の撮影開始時刻を取得する。

    GoPro MP4 の creation_time は撮影終了時刻（ファイル書き込み完了時）なので、
    creation_time - duration で開始時刻を算出する。
    """
    out = run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format_tags=creation_time",
        "-of", "csv=p=0", video_path,
    ], check=False)
    s = out.strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            end_time = dt.replace(tzinfo=timezone.utc).astimezone(JST)
            # creation_time は終了時刻なので duration を引いて開始時刻を得る
            return end_time - timedelta(seconds=duration)
        except ValueError:
            continue
    return None


def build_segment_from_gpx(video_path: str, iphone_points: list[dict]) -> list[dict]:
    """iPhone GPXポイントから動画の撮影時間範囲に対応するセグメントを構築する。

    GPS非搭載GoProの動画に対して、iPhoneのGPXデータを主GPSソースとして使用する。
    タイムラプス動画の場合はGPS実時間を動画長に比例マッピングする。
    """
    if not iphone_points:
        return []

    duration = get_video_duration(video_path)
    if duration <= 0:
        return []

    start_time = get_video_start_time(video_path, duration)
    if start_time is None:
        return []

    end_time = start_time + timedelta(seconds=duration)

    # 撮影時間範囲に含まれるGPXポイントをフィルタ（前後5秒のマージン）
    margin = timedelta(seconds=5)
    pts = [p for p in iphone_points
           if (start_time - margin) <= p["time"] <= (end_time + margin)]
    if not pts:
        return []

    gpx_start = pts[0]["time"]
    gpx_end = pts[-1]["time"]
    gpx_span = (gpx_end - gpx_start).total_seconds()

    # タイムラプス判定: GPS実時間スパンが動画長の2倍以上
    is_timelapse = gpx_span > duration * 2

    # 各ポイントにvideo_tsを付与
    result = []
    for p in pts:
        if is_timelapse and gpx_span > 0:
            # タイムラプス: GPS実時間スパンを動画長に比例マッピング
            video_ts = (p["time"] - gpx_start).total_seconds() / gpx_span * duration
        else:
            # 通常動画: 撮影開始時刻からの経過秒数
            video_ts = (p["time"] - start_time).total_seconds()
            video_ts = max(0.0, min(video_ts, duration))

        result.append({
            "time": p["time"],
            "lat": p["lat"],
            "lon": p["lon"],
            "alt": p.get("alt", 0.0),
            "speed_kmh": 0.0,
            "video_ts": video_ts,
        })

    # 速度計算: ポイント間の距離/時間から算出
    for i in range(1, len(result)):
        dt = (result[i]["time"] - result[i-1]["time"]).total_seconds()
        if dt > 0:
            dist_m = haversine_m(result[i-1], result[i])
            result[i]["speed_kmh"] = dist_m / dt * 3.6

    # 5点中央値フィルタで速度を平滑化
    if len(result) >= 5:
        raw_speeds = [p["speed_kmh"] for p in result]
        for i in range(2, len(result) - 2):
            window = sorted(raw_speeds[i-2:i+3])
            result[i]["speed_kmh"] = window[2]  # 中央値

    return result


# ── ファイル収集・ソート ──────────────────────────

def find_mp4_files(mp4_dir: str, date_str: str | None) -> list[str]:
    """ディレクトリからMP4ファイルを収集し、GPS開始時刻でソートして返す"""
    files = sorted(Path(mp4_dir).glob("*.mp4")) + sorted(Path(mp4_dir).glob("*.MP4"))
    files = list(dict.fromkeys(files))  # 重複除去

    if date_str:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        filtered = []
        for f in files:
            # まずファイル名から日付を推定（GoPro命名規則: GOPR0001.MP4 など）
            # GPS取得前の簡易フィルタとしてファイル更新日時も使う
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=JST).date()
            if mtime == target:
                filtered.append(str(f))
        if filtered:
            print(f"  {date_str} のMP4ファイル: {len(filtered)} 件")
            return filtered
        print(f"  警告: {date_str} に一致するファイルが見つかりません。全ファイルを処理します。")

    return [str(f) for f in files]


def get_segment_start_time(points: list[dict]) -> datetime | None:
    return points[0]["time"] if points else None


# ── メイン処理 ────────────────────────────────────

def make_daily_video(mp4_dir: str, date_str: str | None, output_path: str, fps: float,
                     health_export_dir: str | None = None):
    # ── 1. ファイル収集 ───────────────────────────
    print("[1/5] MP4ファイルを収集中...")
    files = find_mp4_files(mp4_dir, date_str)
    if not files:
        print("エラー: MP4ファイルが見つかりません。")
        sys.exit(1)

    # ── 2. iPhone GPX先読み + GPS抽出 + 時刻順ソート ──
    print("[2/5] GPS抽出・精査中...")

    # iPhone GPXを先に読み込み（GPS非搭載GoProのフォールバック用）
    iphone_all_points: list[dict] = []
    if health_export_dir:
        # 全動画の時間範囲を取得（iPhone GPX検索用）
        all_video_times: list[tuple[datetime, datetime]] = []
        for fpath in files:
            dur = get_video_duration(fpath)
            vstart = get_video_start_time(fpath, dur)
            if vstart and dur > 0:
                all_video_times.append((vstart, vstart + timedelta(seconds=dur)))

        if all_video_times:
            earliest = min(t[0] for t in all_video_times)
            latest = max(t[1] for t in all_video_times)
            print("  HealthKit: ワークアウトGPXを検索中...")
            gpx_paths = find_matching_workout_gpx(health_export_dir, earliest, latest)
            if not gpx_paths:
                # フォールバック: ファイル名の日付で直接検索
                search_date = date_str or earliest.strftime("%Y-%m-%d")
                gpx_paths = find_gpx_by_date(health_export_dir, search_date)
                if gpx_paths:
                    print(f"    → ワークアウト時刻マッチなし、ファイル名で {len(gpx_paths)} 件発見")
            if gpx_paths:
                for gp in gpx_paths:
                    print(f"    GPX読み込み: {Path(gp).name}")
                    iphone_all_points.extend(parse_gpx_route(gp))
                iphone_all_points.sort(key=lambda p: p["time"])
                print(f"    → iPhone GPS {len(iphone_all_points)} 点")
            else:
                print("    → 該当するワークアウトGPXなし")

    # 各ファイルのGPS抽出（GPS無しファイルはiPhone GPXで補完）
    segments = []
    for fpath in files:
        raw = extract_gps_gpmf(fpath)
        if not raw:
            if iphone_all_points:
                # iPhone GPXを主GPSソースとして使用
                pts = build_segment_from_gpx(fpath, iphone_all_points)
                if pts:
                    print(f"  📱 iPhone GPS使用: {Path(fpath).name} ({len(pts)}点)")
                    segments.append({
                        "path":        fpath,
                        "points":      pts,
                        "local_dists": calc_distance(pts),
                        "dist_offset": 0.0,
                        "gps_source":  "iphone",
                    })
                    continue
            print(f"  ⚠ GPS無し: {Path(fpath).name} をスキップ")
            continue
        pts = average_gps_by_second(raw)
        pts = clean_gps_points(pts)
        if not pts:
            continue
        segments.append({
            "path":        fpath,
            "points":      pts,
            "local_dists": calc_distance(pts),   # セグメント内の累積距離
            "dist_offset": 0.0,                  # あとで設定
            "gps_source":  "gopro",
        })

    if not segments:
        print("エラー: 有効なGPSデータを持つファイルがありません。")
        sys.exit(1)

    # GPS開始時刻でソート
    segments.sort(key=lambda s: get_segment_start_time(s["points"]) or datetime.min.replace(tzinfo=JST))

    # ── HealthKitデータ取得 ────────────────────────
    hr_data: list[dict] = []
    if health_export_dir:
        export_xml = os.path.join(health_export_dir, "export.xml")
        all_start = min(get_segment_start_time(s["points"]) for s in segments)
        all_end   = max(s["points"][-1]["time"] for s in segments)

        # 心拍数データ
        if os.path.exists(export_xml):
            print("  HealthKit: 心拍数データを読み込み中...")
            hr_data = parse_heartrate_from_healthkit(export_xml, all_start, all_end)
            print(f"    → 心拍数 {len(hr_data)} 件")

        # GPS搭載GoProセグメントのみiPhoneデータと融合
        if iphone_all_points:
            for seg in segments:
                if seg.get("gps_source") != "gopro":
                    continue
                seg["points"] = fuse_gps_points(seg["points"], iphone_all_points)
                n_fused = sum(1 for p in seg["points"] if p.get("source") == "fused")
                if n_fused:
                    print(f"    {Path(seg['path']).name}: {n_fused} 点融合")
                # 融合後に距離を再計算
                seg["local_dists"] = calc_distance(seg["points"])

    # 距離オフセットを設定（前セグメントの累積距離を引き継ぐ）
    cumulative = 0.0
    for seg in segments:
        seg["dist_offset"] = cumulative
        cumulative += seg["local_dists"][-1]

    total_frames = sum(len(s["points"]) for s in segments)
    total_dist   = cumulative
    print(f"  → {len(segments)} ファイル / 合計 {total_frames} フレーム / 総距離 {total_dist:.2f} km")
    for i, seg in enumerate(segments):
        t = get_segment_start_time(seg["points"])
        print(f"     [{i+1}] {Path(seg['path']).name}  開始: {t.strftime('%H:%M:%S') if t else '?'}  "
              f"{seg['local_dists'][-1]:.2f}km  (オフセット: {seg['dist_offset']:.2f}km)")

    # ── 3. フレーム生成 ───────────────────────────
    print("[3/5] フレームを生成中...")
    with tempfile.TemporaryDirectory(dir=mp4_dir) as tmpdir:
        frame_dir = Path(tmpdir) / "frames"
        frame_dir.mkdir()

        frame_no  = 0
        for seg_idx, seg in enumerate(segments):
            pts      = seg["points"]
            l_dists  = seg["local_dists"]
            offset   = seg["dist_offset"]
            duration = get_video_duration(seg["path"])

            # GPMFパケットタイムスタンプ(video_ts)による直接同期
            n_pts = len(pts)
            has_video_ts = any(p.get("video_ts") is not None for p in pts)
            gps_span = (pts[-1]["time"] - pts[0]["time"]).total_seconds() if n_pts > 1 else 0.0
            print(f"  {Path(seg['path']).name}: 動画長={duration:.1f}s  GPS={n_pts}点 GPS実時間={gps_span:.1f}s  "
                  f"同期方式={'GPMFパケットタイム' if has_video_ts else 'GPS時刻比例'}")
            # デバッグ: 先頭・末尾のGPS→動画マッピングを表示
            for di in [0, min(5, n_pts-1), n_pts-1]:
                dp = pts[di]
                vts = dp.get("video_ts")
                print(f"    GPS[{di}] {dp['time'].strftime('%H:%M:%S')} "
                      f"({dp['lat']:.5f},{dp['lon']:.5f}) → video_ts={vts:.2f}s" if vts is not None
                      else f"    GPS[{di}] {dp['time'].strftime('%H:%M:%S')} "
                      f"({dp['lat']:.5f},{dp['lon']:.5f}) → video_ts=なし")

            # セグメント内の心拍数を補間
            seg_hr_values = _interpolate_hr_for_dists(pts, l_dists, hr_data) if hr_data else None

            for local_idx, point in enumerate(pts):
                global_dist = offset + l_dists[local_idx]
                frame_label = f"[{seg_idx+1}/{len(segments)}] {Path(seg['path']).name} {local_idx+1}/{len(pts)}"
                print(f"  フレーム {frame_no+1}/{total_frames}  {frame_label}  {point['time'].strftime('%H:%M:%S')}  {global_dist:.2f}km", end="\r")

                # GoProフレーム抽出: GPMFパケットのvideo_tsで直接シーク
                frame_path = str(frame_dir / f"vf_{frame_no:06d}.jpg")
                if duration > 0:
                    if point.get("video_ts") is not None:
                        # GPMFパケットタイムスタンプを直接使用（最も正確）
                        video_ts = point["video_ts"]
                    elif gps_span > 0:
                        # フォールバック: GPS経過時間の比例マッピング
                        gps_elapsed = (point["time"] - pts[0]["time"]).total_seconds()
                        video_ts = gps_elapsed * (duration / gps_span)
                    else:
                        video_ts = 0.0
                    video_ts = max(0.0, min(video_ts, duration - 0.1))
                    extract_video_frame(seg["path"], video_ts, frame_path)
                video_frame = None
                if os.path.exists(frame_path):
                    try:
                        video_frame = Image.open(frame_path).convert("RGB")
                    except Exception:
                        pass

                # 現在の心拍数を取得
                cur_hr = seg_hr_values[local_idx] if seg_hr_values else None

                map_img   = render_map(segments, seg_idx, local_idx, global_dist, (HALF_W, TOP_H))
                stats_img = render_stats_bar(point, global_dist, (OUT_W, STATS_H), heart_rate_bpm=cur_hr)
                graph_img = render_combined_graph(pts, l_dists, local_idx, (OUT_W, GRAPH_H), hr_values=seg_hr_values)

                composed = compose_frame(video_frame, map_img, stats_img, graph_img)
                composed.save(str(frame_dir / f"frame_{frame_no:06d}.png"))
                frame_no += 1

        print(f"\n[4/5] 動画をエンコード中: {output_path}")
        run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-pattern_type", "glob",
            "-i", str(frame_dir / "frame_*.png"),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path,
        ], capture=False, check=True)

    print(f"\n完了! → {output_path}")
    print(f"  合計距離: {total_dist:.2f} km  / {len(segments)} ファイル結合")


def main():
    parser = argparse.ArgumentParser(description="GoPro GPS軌跡動画ジェネレーター（1日分まとめ）")
    parser.add_argument("mp4_dir",                                        help="MP4ファイルが入ったディレクトリ")
    parser.add_argument("--date",   default=None,                         help="対象日付 YYYY-MM-DD（省略時は全MP4）")
    parser.add_argument("-o", "--output", default="output_daily.mp4",     help="出力ファイル名")
    parser.add_argument("--fps",    type=float, default=10.0,             help="出力FPS（デフォルト10）")
    parser.add_argument("--width",  type=int,   default=1920)
    parser.add_argument("--height", type=int,   default=1080)
    parser.add_argument("--health-export", default=None,
                        help="HealthKitエクスポートディレクトリ (export.xmlとworkout-routes/を含む)")
    args = parser.parse_args()

    global OUT_W, OUT_H, TOP_H, STATS_H, GRAPH_H, HALF_W
    OUT_W   = args.width
    OUT_H   = args.height
    TOP_H   = OUT_H // 2
    STATS_H = 60
    GRAPH_H = OUT_H - TOP_H - STATS_H
    HALF_W  = OUT_W // 2

    if not os.path.isdir(args.mp4_dir):
        print(f"エラー: ディレクトリが見つかりません: {args.mp4_dir}")
        sys.exit(1)

    make_daily_video(args.mp4_dir, args.date, args.output, args.fps,
                     health_export_dir=args.health_export)


if __name__ == "__main__":
    main()
