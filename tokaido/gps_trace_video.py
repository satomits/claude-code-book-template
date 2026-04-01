#!/usr/bin/env python3
"""
GoPro GPS軌跡動画ジェネレーター
GoProの動画からGPS情報を抽出して、地図上に軌跡を描いた動画を生成する。

レイアウト:
  ┌──────────────────────────────────────────┐
  │  左上1/2: GoProフレーム │ 右上1/2: 地図    │
  │  (960x540)              │  (960x540)      │
  ├──────────────────────────────────────────┤
  │  日時 | 速度 | 高度 | 距離 (1行テキスト)    │  60px
  ├──────────────────────────────────────────┤
  │  速度・高度グラフ (1920x480)                │
  └──────────────────────────────────────────┘

軌跡の色 (距離グラデーション):
  0-10km: 青, 10-20km: 緑, 20-30km: 黄, 30km+: 赤

GPS処理:
  全フレームのGPSデータを抽出し、1秒ごとに平均化。
  位置差分から速度を再計算し、外れ値補間・中央値フィルタで精査。

Usage:
    python3 gps_trace_video.py <input.mp4> [--output output.mp4] [--fps 10]
"""

import argparse
import functools
import json
import math
import os
import subprocess
import sys
import tempfile
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
TOP_H   = OUT_H // 2                  # 540 - 上半分 (動画 + 地図)
STATS_H = 60                           # 統計バーの高さ
GRAPH_H = OUT_H - TOP_H - STATS_H     # 480 - 速度・高度グラフ
HALF_W  = OUT_W // 2                  # 960

# ── 地図タイル ──────────────────────────────────
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAP_ZOOM = 14

# ── 距離→軌跡色マッピング ─────────────────────────
DIST_COLOR_STOPS = [
    (10.0,         "#2979FF"),   # 青:   0-10km
    (20.0,         "#00C853"),   # 緑:  10-20km
    (30.0,         "#FFD600"),   # 黄:  20-30km
    (float("inf"), "#FF1744"),   # 赤:  30km+
]

# ── フォント ────────────────────────────────────
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

def extract_gps_gpmf(video_path: str) -> list[dict]:
    """exiftool -ee3 で GoPro GPMF の全GPS点を抽出 (サブサンプルも含む全点)"""
    print(f"[1/5] exiftool でGPSデータを抽出中: {video_path}")
    template = "$GPSDateTime|$GPSLatitude|$GPSLongitude|$GPSAltitude|$GPSSpeed3D"
    out = run(["exiftool", "-ee3", "-p", template, video_path], check=False)

    points = []
    for line in out.strip().splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            dt_str  = parts[0].strip()
            lat_str = parts[1].strip()
            lon_str = parts[2].strip()
            alt_str = parts[3].strip() if len(parts) > 3 else "0"

            lat = parse_dms(lat_str)
            lon = parse_dms(lon_str)
            alt = float(alt_str.split()[0]) if alt_str else 0.0
            dt  = parse_gps_datetime(dt_str)
            if lat is not None and lon is not None and dt is not None:
                # speed_kmh は後段の clean_gps_points() で位置差分から再計算する
                points.append({"time": dt, "lat": lat, "lon": lon,
                                "alt": alt, "speed_kmh": 0.0})
        except Exception:
            continue

    if not points:
        print("  ⚠ GPSデータが取得できませんでした。ダミーデータを使用します。")
        return dummy_gps()
    print(f"  → {len(points)} 点取得")
    return points


def average_gps_by_second(points: list[dict]) -> list[dict]:
    """全GPS点を1秒ごとにバケット化して平均をとる"""
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for p in points:
        t = p["time"].replace(microsecond=0)
        buckets[t].append(p)

    result = []
    for t in sorted(buckets.keys()):
        ps = buckets[t]
        result.append({
            "time": t,
            "lat":  sum(p["lat"] for p in ps) / len(ps),
            "lon":  sum(p["lon"] for p in ps) / len(ps),
            "alt":  sum(p["alt"] for p in ps) / len(ps),
            "speed_kmh": 0.0,  # clean_gps_points() で上書き
        })
    return result


def clean_gps_points(points: list[dict], max_speed_kmh: float = 50.0) -> list[dict]:
    """
    GPS外れ値を除去・補間し、速度を位置差分から再計算する。

    1. 隣接点間の implied speed が max_speed_kmh を超えたら位置の外れ値とみなす
    2. 外れ値の lat/lon/alt を前後の有効点で線形補間
    3. 補間後の位置から速度を再計算 (距離/時間 → km/h)
    4. 中央値フィルタ (window=5) でスパイクをさらに除去
    """
    if len(points) < 3:
        return points

    R = 6371000.0

    def haversine_m(p1: dict, p2: dict) -> float:
        lat1, lon1 = math.radians(p1["lat"]), math.radians(p1["lon"])
        lat2, lon2 = math.radians(p2["lat"]), math.radians(p2["lon"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        return 2 * R * math.asin(math.sqrt(max(0.0, a)))

    # ── Step 1: 位置外れ値をマーク ──────────────────
    valid = [True] * len(points)
    for i in range(1, len(points)):
        dist_m = haversine_m(points[i-1], points[i])
        dt     = (points[i]["time"] - points[i-1]["time"]).total_seconds()
        if dt > 0 and (dist_m / dt * 3.6) > max_speed_kmh:
            valid[i] = False

    n_bad = valid.count(False)
    if n_bad:
        print(f"  → GPS外れ値 {n_bad} 点を補間")

    # ── Step 2: 外れ値を線形補間 ─────────────────────
    cleaned = [dict(p) for p in points]
    for i in range(1, len(points) - 1):
        if valid[i]:
            continue
        prev_i = next((j for j in range(i - 1, -1, -1) if valid[j]), None)
        next_i = next((j for j in range(i + 1, len(points))  if valid[j]), None)
        if prev_i is None or next_i is None:
            continue
        t_total = (points[next_i]["time"] - points[prev_i]["time"]).total_seconds()
        t_ratio = (points[i]["time"]      - points[prev_i]["time"]).total_seconds() / max(t_total, 1e-9)
        for key in ("lat", "lon", "alt"):
            cleaned[i][key] = (points[prev_i][key]
                               + (points[next_i][key] - points[prev_i][key]) * t_ratio)

    # ── Step 3: 位置差分から速度を再計算 ─────────────
    raw_speeds = [0.0]
    for i in range(1, len(cleaned)):
        dist_m = haversine_m(cleaned[i-1], cleaned[i])
        dt     = (cleaned[i]["time"] - cleaned[i-1]["time"]).total_seconds()
        raw_speeds.append((dist_m / dt * 3.6) if dt > 0 else 0.0)

    # ── Step 4: 中央値フィルタ (window=5) ─────────────
    W = 5
    smoothed: list[float] = []
    for i in range(len(raw_speeds)):
        win = raw_speeds[max(0, i - W // 2) : i + W // 2 + 1]
        smoothed.append(sorted(win)[len(win) // 2])

    return [{**p, "speed_kmh": smoothed[i]} for i, p in enumerate(cleaned)]


def dummy_gps() -> list[dict]:
    """テスト用ダミーGPSデータ (東京出発、1秒ごと 1時間分)"""
    print("  → ダミーGPSデータを生成")
    base_lat, base_lon = 35.6812, 139.7671
    base_time = datetime(2024, 3, 1, 9, 0, 0, tzinfo=JST)
    return [
        {
            "time":      base_time + timedelta(seconds=i),
            "lat":       base_lat - i * 0.00003,
            "lon":       base_lon + i * 0.000008,
            "alt":       50 + 30 * math.sin(i * 0.02),
            "speed_kmh": 15 + 10 * abs(math.sin(i * 0.05)),
        }
        for i in range(3600)
    ]


def parse_dms(s: str) -> float | None:
    """'35 deg 40\' 50.00" N' などの形式を十進度に変換"""
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


def calc_distance(points: list[dict]) -> list[float]:
    """各ポイントまでの累積走行距離 (km) を計算"""
    R = 6371.0
    dists = [0.0]
    for i in range(1, len(points)):
        lat1 = math.radians(points[i-1]["lat"])
        lon1 = math.radians(points[i-1]["lon"])
        lat2 = math.radians(points[i]["lat"])
        lon2 = math.radians(points[i]["lon"])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        dists.append(dists[-1] + 2 * R * math.asin(math.sqrt(max(0.0, a))))
    return dists


def dist_to_color(dist_km: float) -> str:
    """走行距離 (km) から軌跡の色を返す"""
    for threshold, color in DIST_COLOR_STOPS:
        if dist_km < threshold:
            return color
    return DIST_COLOR_STOPS[-1][1]


# ── 逆ジオコーディング ────────────────────────────

@functools.lru_cache(maxsize=512)
def _fetch_location_name(lat_r: float, lon_r: float) -> str:
    """
    Nominatim 逆ジオコーディング (緯度経度 → 都道府県・市町村名)。
    lru_cache でキャッシュするため引数は 0.01度丸め済みの値を渡す。
    """
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat_r, "lon": lon_r, "format": "json", "accept-language": "ja"},
            headers={"User-Agent": "gps_trace_video/1.0"},
            timeout=5,
        )
        addr = resp.json().get("address", {})
        prefecture  = addr.get("state", "")
        municipality = (
            addr.get("city") or addr.get("town") or
            addr.get("village") or addr.get("county") or ""
        )
        if prefecture and municipality:
            return f"{prefecture} {municipality}"
        return prefecture or municipality
    except Exception:
        return ""


def get_location_name(lat: float, lon: float) -> str:
    """GPS座標から都道府県・市町村名を取得 (~1km 単位でキャッシュ)"""
    return _fetch_location_name(round(lat, 2), round(lon, 2))


# ── レンダリング ──────────────────────────────────

def extract_video_frame(video_path: str, timestamp_sec: float, out_path: str):
    """ffmpeg で指定秒数のフレームを抽出"""
    run([
        "ffmpeg", "-y", "-ss", str(timestamp_sec),
        "-i", video_path,
        "-vframes", "1", "-q:v", "2", out_path,
    ], capture=True, check=False)


def render_map(
    points: list[dict],
    current_idx: int,
    distances: list[float],
    size: tuple[int, int],
) -> Image.Image:
    """
    現在地点を中心にルート付き地図を生成。
    走行済み軌跡は距離に応じた色でセグメント表示。
    地図左下に逆ジオコーディングで取得した都道府県・市町村名を表示。
    """
    lat = points[current_idx]["lat"]
    lon = points[current_idx]["lon"]

    m = StaticMap(size[0], size[1], url_template=TILE_URL)

    # 全ルートをグレーで下書き
    if len(points) > 1:
        all_coords = [(p["lon"], p["lat"]) for p in points]
        m.add_line(Line(all_coords, "#444444", 2))

    # 走行済み軌跡を距離帯ごとに色分け (帯境界で前点を引き継ぎ連続性を保つ)
    if current_idx > 0:
        seg_coords = [(points[0]["lon"], points[0]["lat"])]
        seg_color  = dist_to_color(distances[0])

        for i in range(1, current_idx + 1):
            color = dist_to_color(distances[i])
            coord = (points[i]["lon"], points[i]["lat"])
            if color == seg_color:
                seg_coords.append(coord)
            else:
                if len(seg_coords) >= 2:
                    m.add_line(Line(seg_coords, seg_color, 5))
                seg_coords = [seg_coords[-1], coord]
                seg_color  = color
        if len(seg_coords) >= 2:
            m.add_line(Line(seg_coords, seg_color, 5))

    # 現在位置マーカー (白縁 + 距離色)
    cur_color = dist_to_color(distances[current_idx])
    m.add_marker(CircleMarker((lon, lat), "#FFFFFF", 16))
    m.add_marker(CircleMarker((lon, lat), cur_color,  11))

    try:
        img = m.render(zoom=MAP_ZOOM, center=[lon, lat])
    except Exception as e:
        print(f"  ⚠ 地図レンダリングエラー: {e}")
        img = Image.new("RGB", size, "#c8e6c9")

    img = img.convert("RGB").resize(size, Image.LANCZOS)

    # ── 都道府県・市町村名をオーバーレイ ──────────────
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
        bx0 = pad
        by0 = size[1] - th - pad * 2 - 4
        bx1 = bx0 + tw + pad * 2
        by1 = size[1] - pad

        # 半透明背景 (RGBA → paste)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rounded_rectangle([bx0, by0, bx1, by1], radius=6, fill=(0, 0, 0, 160))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((bx0 + pad, by0 + 4), location, font=font, fill="#FFFFFF")

    return img


def render_stats_bar(
    point: dict,
    distance_km: float,
    size: tuple[int, int],
) -> Image.Image:
    """日時・速度・高度・距離を1行で表示するバーを生成"""
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
        ("速度",  f"{point['speed_kmh']:.1f} km/h",     "#40C4FF"),
        ("高度",  f"{point['alt']:.0f} m",               "#FFD740"),
        ("距離",  f"{distance_km:.2f} km",               "#69F0AE"),
    ]

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


def render_combined_graph(
    points: list[dict],
    current_idx: int,
    distances: list[float],
    size: tuple[int, int],
) -> Image.Image:
    """速度 (右軸・オレンジ) と高度 (左軸・水色) の複合グラフを生成"""
    fig, ax1 = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    fig.patch.set_facecolor("#0D1117")
    ax1.set_facecolor("#161B22")

    alts   = [p["alt"]       for p in points]
    speeds = [p["speed_kmh"] for p in points]
    dists  = distances
    ci     = current_idx

    ax2 = ax1.twinx()

    # 高度 (左軸・水色)
    ax1.fill_between(dists[:ci+1], alts[:ci+1], alpha=0.2, color="#29B6F6")
    ax1.plot(dists, alts,               color="#2a3a4a", linewidth=1.0, zorder=1)
    ax1.plot(dists[:ci+1], alts[:ci+1], color="#29B6F6", linewidth=2.0, zorder=2)
    ax1.set_ylabel("高度 (m)", color="#29B6F6", fontsize=10)
    ax1.tick_params(axis="y", colors="#29B6F6")

    # 速度 (右軸・オレンジ)
    ax2.plot(dists, speeds,                 color="#2a3a4a", linewidth=1.0, zorder=1)
    ax2.plot(dists[:ci+1], speeds[:ci+1],   color="#FF9100", linewidth=2.0, zorder=2)
    ax2.set_ylabel("速度 (km/h)", color="#FF9100", fontsize=10)
    ax2.tick_params(axis="y", colors="#FF9100")

    # 現在位置
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
    ax1.legend(handles=legend_lines, loc="upper left",
               facecolor="#161B22", edgecolor="#30363D",
               labelcolor="#FFFFFF", fontsize=9)

    plt.tight_layout(pad=0.5)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
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
    """全パーツを合成して最終フレームを生成"""
    canvas = Image.new("RGB", (OUT_W, OUT_H), "#0D1117")

    vf = (video_frame.resize((HALF_W, TOP_H), Image.LANCZOS)
          if video_frame else Image.new("RGB", (HALF_W, TOP_H), "#1A1A2E"))
    canvas.paste(vf, (0, 0))
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


def make_video(video_path: str, output_path: str, fps: float = 10.0):
    # ── 1. GPS データ全点抽出 ─────────────────────
    all_points = extract_gps_gpmf(video_path)
    if not all_points:
        print("エラー: GPS データが取得できませんでした。")
        sys.exit(1)

    # ── 2. 1秒ごとに平均化 + 外れ値除去・速度再計算 ──
    print("[2/5] 1秒ごとに平均化 + GPS精査中...")
    points    = average_gps_by_second(all_points)
    points    = clean_gps_points(points)
    distances = calc_distance(points)
    print(f"  → {len(points)} フレーム / 総距離 {distances[-1]:.2f} km")

    # ── 3. 動画の長さを取得 ───────────────────────
    duration = get_video_duration(video_path)
    print(f"[3/5] 動画長: {duration:.1f}秒")

    # ── 4. 各フレームをレンダリング ────────────────
    print("[4/5] フレームを生成中...")
    with tempfile.TemporaryDirectory() as tmpdir:
        frame_dir = Path(tmpdir) / "frames"
        frame_dir.mkdir()

        total = len(points)
        for i, point in enumerate(points):
            print(f"  フレーム {i+1}/{total}  {point['time'].strftime('%H:%M:%S')}", end="\r")

            frame_path = str(frame_dir / f"vf_{i:05d}.jpg")
            if duration > 0:
                elapsed = (point["time"] - points[0]["time"]).total_seconds()
                elapsed = min(elapsed, duration - 0.1)
                extract_video_frame(video_path, elapsed, frame_path)
            video_frame = None
            if os.path.exists(frame_path):
                try:
                    video_frame = Image.open(frame_path).convert("RGB")
                except Exception:
                    pass

            map_img   = render_map(points, i, distances, (HALF_W, TOP_H))
            stats_img = render_stats_bar(point, distances[i], (OUT_W, STATS_H))
            graph_img = render_combined_graph(points, i, distances, (OUT_W, GRAPH_H))

            composed  = compose_frame(video_frame, map_img, stats_img, graph_img)
            composed.save(str(frame_dir / f"frame_{i:05d}.png"))

        print(f"\n[5/5] 動画をエンコード中: {output_path}")
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


def main():
    parser = argparse.ArgumentParser(description="GoPro GPS軌跡動画ジェネレーター")
    parser.add_argument("input",                                      help="入力 GoPro 動画ファイル (.mp4)")
    parser.add_argument("-o", "--output", default="output_trace.mp4", help="出力動画ファイル名")
    parser.add_argument("--fps",    type=float, default=10.0,  help="出力FPS (デフォルト10、=10倍速)")
    parser.add_argument("--width",  type=int,   default=1920,  help="出力幅")
    parser.add_argument("--height", type=int,   default=1080,  help="出力高さ")
    args = parser.parse_args()

    global OUT_W, OUT_H, TOP_H, STATS_H, GRAPH_H, HALF_W
    OUT_W   = args.width
    OUT_H   = args.height
    TOP_H   = OUT_H // 2
    STATS_H = 60
    GRAPH_H = OUT_H - TOP_H - STATS_H
    HALF_W  = OUT_W // 2

    if not os.path.exists(args.input):
        print(f"エラー: ファイルが見つかりません: {args.input}")
        sys.exit(1)

    make_video(args.input, args.output, args.fps)


if __name__ == "__main__":
    main()
