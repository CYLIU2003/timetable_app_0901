from typing import Optional
# --- Tkinter/ブラウザ/スレッド用インポート ---
# --- Tkinter/ブラウザ/スレッド用インポート ---
import tkinter as tk
import webbrowser
import threading
# -*- coding: utf-8 -*-
"""
App A – Tokyu Departure Board WebApp
FULL SOURCE rev-2025-05-18  (★ CSV 対応版)

機能
──────────────────────────────────────────
▪ 発車案内   (CSV ➜ walk/run advice)
▪ 天気       Tsukumijima Weather JSON FULL（3日分）
▪ ニュース   NHK RSS + Google News
▪ 運行情報   Tokyu scrape + ODPT → 各社平常 or 異常のみ（日本語路線名＋ロゴ付き）
──────────────────────────────────────────
"""

import atexit
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import os
import sqlite3
import subprocess
import html
import requests
import pandas as pd
import feedparser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, url_for, request  # request を追加
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ──────────────────────────────────────────
#  ディレクトリ・ファイルパス定義
# ──────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent              # timetable-app/
DATA_DIR   = BASE_DIR / "timetable_data"                  # ★ 時刻表置き場 (CSV/Excel)
STATIC_DIR = BASE_DIR / "static"                          # 画像・CSS・JS
STATUS_DB_PATH = Path(os.getenv("ODPT_STATUS_DB", BASE_DIR / "runtime" / "odpt_status.db"))
STATUS_POLLER_EXECUTABLE = Path(
    os.getenv(
        "ODPT_POLLER_EXECUTABLE",
        BASE_DIR / "rust" / "odpt_poller" / "target" / "release" / ("odpt_poller.exe" if os.name == "nt" else "odpt_poller"),
    )
)
STATUS_POLLER_INTERVAL_SECONDS = int(os.getenv("ODPT_POLL_INTERVAL_SECONDS", "300"))
STATUS_POLLER_AUTO_START = os.getenv("ODPT_POLLER_AUTO_START", "1") != "0"
STATUS_STARTUP_CHECKS = os.getenv("ODPT_STARTUP_CHECKS", "0") == "1"
ODPT_POLLER_PROCESS: subprocess.Popen | None = None

# バス Excel ファイル
bus_timetable_file  = DATA_DIR / "timetablebus.xlsx"
bus_timetable_file2 = DATA_DIR / "timetablebus2.xlsx"
bus_timetable_file3 = DATA_DIR / "timetablebus3.xlsx"

# Flask アプリ
app = Flask(__name__)
# app.config["SERVER_NAME"] = "127.0.0.1:5000"  # ← 外部アクセス対応のためコメントアウト
app.config["PREFERRED_URL_SCHEME"] = "http"

# ──────────────────────────────────────────
#  ユーティリティ : 電車 (CSV)
# ──────────────────────────────────────────
# _DEST_MAP は ROUTES に移行するため削除

_DAY_MAP = {   # datetime.weekday() ➜ ファイル名用タグ
    0: "weekday", 1: "weekday", 2: "weekday", 3: "weekday", 4: "weekday",
    5: "holiday",  # 土曜日も休日ダイヤを参照するように変更
    6: "holiday",
}

def fetch_train_schedule(line_code: str, dest_tag: str) -> list[dict[str, str]]:
    """
    指定された路線の電車時刻表を CSV から読み込んで
    {"time": "HH:MM", "type": "種別", "dest": "行き先"} の辞書のリストを返す
      line_code: "OM", "TY", "MG", "BL" など
      dest_tag : "Ooimachi", "Mizonokuchi", "Shibuya", "Yokohama", "Meguro", "Hiyoshi", "Azamino", "Shonandai" など
    """
    # 1) 対象 CSV ファイル決定
    today_tag = _DAY_MAP[datetime.now().weekday()]
    csv_path  = DATA_DIR / f"timetable_{line_code}_{today_tag}_{dest_tag}.csv"

    # ブルーライン用のデバッグ出力を追加
    if line_code == "BL":
        print(f"[DEBUG] 読み込み試行: {csv_path} (存在: {csv_path.exists()})")

    if not csv_path.exists():
        print(f"[WARN] CSV not found: {csv_path}")
        return []

    # 2) CSV 読込
    df = None
    try:
        # header=0 を明示し、1行目をヘッダーとして扱う
        # keep_default_na=False で、空欄を空文字列として読み込む
        # dtype=str を追加して、すべての列を文字列として読み込むことで、予期せぬ型変換を防ぐ
        df = pd.read_csv(csv_path, encoding="utf-8", header=0, keep_default_na=False, dtype=str)
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(csv_path, encoding="cp932", header=0, keep_default_na=False, dtype=str)
        except Exception as e_cp932:
            print(f"[ERROR] CSV read error (cp932): {csv_path} - {e_cp932}")
            return []
    except Exception as e:
        print(f"[ERROR] CSV read error (utf-8): {csv_path} - {e}")
        return []

    if df is None or df.empty:
        # print(f"[INFO] CSV is empty or failed to load: {csv_path}") # 既に読み込み失敗時にエラーが出るため、重複を避ける
        return []

    # 3) 時刻・種別・行き先抽出
    out: list[dict[str, str]] = []
    
    num_columns = len(df.columns)
    if num_columns == 0:
        print(f"[WARN] CSV has no columns: {csv_path}")
        return []

    # デバッグ用に列名を出力したい場合は以下のコメントを解除
    # print(f"[DEBUG] CSV Columns for {csv_path}: {df.columns.tolist()}") 

    for index, row in df.iterrows():
        try:
            time_str = str(row.iloc[0]).strip()
            if not time_str:
                # print(f"[DEBUG] Skipping row due to empty time: {row.to_list()} in {csv_path}")
                continue
            
            try:
                # "H:MM" または "HH:MM" 形式をパースし、"HH:MM" に正規化
                parts = time_str.split(':')
                if len(parts) == 2:
                    h, m = int(parts[0]), int(parts[1])
                    formatted_time = f"{h:02d}:{m:02d}"
                    datetime.strptime(formatted_time, "%H:%M") # 正当性チェック
                else:
                    # print(f"[DEBUG] Skipping row due to invalid time format '{time_str}': {row.to_list()} in {csv_path}")
                    continue
            except ValueError:
                # print(f"[DEBUG] Skipping row due to invalid time format '{time_str}': {row.to_list()} in {csv_path}")
                continue

            train_type = ""
            if num_columns > 1:
                train_type = str(row.iloc[1]).strip()
            
            destination = ""
            if num_columns > 2:
                destination = str(row.iloc[2]).strip()
            
            if train_type.lower() in ["nan", "na", "<na>", "-", "ー"]: train_type = ""
            if destination.lower() in ["nan", "na", "<na>", "-", "ー"]: destination = ""

            out.append({
                "time": formatted_time,
                "type": train_type,
                "dest": destination
            })
        except (ValueError, TypeError) as e_parse:
            # print(f"[DEBUG] Skipping row due to parse error ({e_parse}): {row.to_list()} in {csv_path}")
            pass
        except IndexError as e_index: 
            # print(f"[DEBUG] Skipping row due to IndexError ({e_index}): {row.to_list()} in {csv_path}")
            pass
            
    if not out and not df.empty: # CSVにデータ行はあるが、有効な時刻情報が抽出できなかった場合
        print(f"[INFO] No valid schedule entries extracted from {csv_path}. Please check CSV format (time in 1st col, etc.) and content.")
        # さらに詳細なデバッグが必要な場合、以下のコメントを解除
        # print(f"[DEBUG] First 5 rows of CSV {csv_path} that might have issues:\n{df.head().to_string()}")

    return sorted(out, key=lambda x: x["time"])


# ──────────────────────────────────────────
#  ユーティリティ : バス (従来どおり Excel)
# ──────────────────────────────────────────
def fetch_bus_schedule(sheet: str, col: str, path: Path) -> list[str]:
    """バス時刻表（行方向：時、列方向：分）を HH:MM リストで返す"""
    # --- デバッグ: 実際のシート名一覧を出力 ---
    try:
        print(f"[DEBUG] Excelファイル: {path}")
        print(f"[DEBUG] シート一覧: {pd.ExcelFile(path).sheet_names}")
    except Exception as e:
        print(f"[ERROR] Excelファイル/シート一覧取得失敗: {e}")
    
    print(f"[DEBUG] 読み込みシート名: {sheet}")
    df = pd.read_excel(path, sheet_name=sheet)
    print(f"[DEBUG] 読み込んだ列名: {df.columns.tolist()}")
    if "時" not in df.columns:
        df.rename(columns={df.columns[0]: "時"}, inplace=True)
    if col not in df.columns:
        print(f"[WARN] 指定列 '{col}' が見つかりません。第2列 '{df.columns[1]}' を使用します。")
        col = df.columns[1]
    else:
        print(f"[DEBUG] 使用列: {col}")
    out = []
    for _, row in df.iterrows():
        h = str(row["時"]).strip()
        if not h.isdigit() or pd.isna(row[col]):
            continue
        for m in str(row[col]).split():
            if m.isdigit():
                out.append(f"{h.zfill(2)}:{m.zfill(2)}")
    return out


def sheet_name(kind: str, key: Optional[str] = None) -> str:
    """曜日判定してシート名を返すヘルパ（バス用のみ）"""
    wd = datetime.now().weekday()
    if kind in ("bus", "bus_2"):
        return f"{'平日' if wd < 5 else '土休日'}_{key}"
    if kind == "bus_3":
        if wd < 5:
            return f"平日_{key}"
        if wd == 5:
            return f"土曜_{key}"
        return f"日休日_{key}"
    raise ValueError("kind error")


def remaining(dep_time: str) -> timedelta:
    """HH:MM 形式 ➜ 出発までの残り time delta"""
    now = datetime.now()
    dep = datetime.strptime(dep_time, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    if dep < now:
        dep += timedelta(days=1)
    return dep - now


def fetch_bus_schedule_csv(bus_type: str, dest_tag: str) -> list[dict[str, str]]:
    """
    バス時刻表をCSVから読み込んで電車と同じ形式で返す
    {"time": "HH:MM", "type": "", "dest": "行き先"} の辞書のリスト
    """
    # 曜日に応じたファイル選択
    wd = datetime.now().weekday()
    day_tag = "weekday"
    if wd == 5:  # 土曜日
        day_tag = "saturday"
    elif wd == 6:  # 日曜日
        day_tag = "holiday"
    
    # CSVファイルパス
    csv_path = DATA_DIR / f"timetable_BUS_{day_tag}_{dest_tag}.csv"
    
    print(f"[DEBUG] バスCSV読み込み試行: {csv_path} (存在: {csv_path.exists()})")
    
    if not csv_path.exists():
        print(f"[WARN] バスCSV not found: {csv_path}")
        return []
    
    # CSV読込
    df = None
    try:
        df = pd.read_csv(csv_path, encoding="utf-8", header=0, keep_default_na=False, dtype=str)
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(csv_path, encoding="cp932", header=0, keep_default_na=False, dtype=str)
        except Exception as e_cp932:
            print(f"[ERROR] バスCSV read error (cp932): {csv_path} - {e_cp932}")
            return []
    except Exception as e:
        print(f"[ERROR] バスCSV read error (utf-8): {csv_path} - {e}")
        return []
    
    if df is None or df.empty:
        return []
    
    # 時刻・行き先抽出
    out = []
    for _, row in df.iterrows():
        try:
            time_str = str(row.iloc[0]).strip()
            if not time_str:
                continue
            
            # 時刻のフォーマット
            try:
                parts = time_str.split(':')
                if len(parts) == 2:
                    h, m = int(parts[0]), int(parts[1])
                    formatted_time = f"{h:02d}:{m:02d}"
                    datetime.strptime(formatted_time, "%H:%M")  # 正当性チェック
                else:
                    continue
            except ValueError:
                continue
            
            # 行き先
            destination = ""
            if len(df.columns) > 1:
                destination = str(row.iloc[1]).strip()
            
            if destination.lower() in ["nan", "na", "<na>", "-", "ー"]:
                destination = ""
            
            out.append({
                "time": formatted_time,
                "type": "",  # バスの種別は空
                "dest": destination
            })
        except (ValueError, TypeError, IndexError):
            pass
    
    return sorted(out, key=lambda x: x["time"])


# ──────────────────────────────────────────
#  発車案内ルート定義
# ──────────────────────────────────────────
ROUTES = [
    dict(
        label="東急大井町線　尾山台駅",
        type="train",
        line_code="OM",
        directions=[
            dict(column="大井町方面", dest_tag="Ooimachi"),
            dict(column="溝の口方面", dest_tag="Mizonokuchi"),
        ],
        max=3,
        walk=14,
        run=10,
    ),
    dict(
        label="東急東横線　田園調布駅", # ラベル変更
        type="train",
        line_code="TY",
        directions=[
            dict(column="渋谷方面", dest_tag="Shibuya"),
            dict(column="横浜方面", dest_tag="Yokohama"),
        ],
        max=3,
        walk=30, # 所要時間変更
        run=25,  # 所要時間変更
    ),
    dict(
        label="東急目黒線　田園調布駅", # ラベル変更
        type="train",
        line_code="MG",
        directions=[
            dict(column="目黒方面", dest_tag="Meguro"),
            dict(column="日吉方面", dest_tag="Hiyoshi"),
        ],
        max=3,
        walk=30, # 所要時間変更
        run=25,  # 所要時間変更
    ),
    dict(
        label="横浜市営地下鉄・ブルーライン 中川駅",
        type="train",
        line_code="BL", # ブルーラインの路線コード (仮)
        directions=[
            dict(column="あざみ野方面", dest_tag="Azamino"),
            dict(column="湘南台方面", dest_tag="Shonandai"),
        ],
        max=3, # 表示件数 (他に合わせて3件)
        walk=15,
        run=10,
    ),
    # --- ここから追加 ---
    dict(
        label="玉11　東京都市大学南入口",
        type="bus",
        file=bus_timetable_file,
        directions=[
            dict(column="多摩川駅方面", sheet_direction="多摩川"),
            dict(column="二子玉川駅方面", sheet_direction="二子玉川"),
        ],
        max=2,
        walk=7,
        run=5,
    ),
    dict(
        label="園02　東京都市大学北入口",
        type="bus_3",
        file=bus_timetable_file3,
        directions=[
            dict(column="千歳船橋駅方面", sheet_direction="千歳船橋"),
            dict(column="田園調布方面", sheet_direction="田園調布"),
        ],
        max=2,
        walk=7,
        run=5,
    ),
    dict(
        label="等01　東京都市大学前",
        type="bus_2",
        file=bus_timetable_file2,
        directions=[
            dict(column="等々力循環", sheet_direction="等々力"),
        ],
        max=2,
        walk=7,
        run=5,
    ),
    # --- ここから追加 ---
    dict(
        label="東急バス　長徳寺前",
        type="bus_csv",
        directions=[
            dict(column="鷺沼駅方面", dest_tag="Saginuma"),
            dict(column="センター北駅方面", dest_tag="CenterKita"),
        ],
        max=3,
        walk=10,
        run=7,
    ),
    # --- ここまで追加 ---
]

# ──────────────────────────────────────────
#  API: 発車案内
# ──────────────────────────────────────────
@app.route("/api/schedule")
def api_schedule():
    labs = ["先発", "次発", "次々発"]
    res = {"current_time": datetime.now().strftime("%H:%M:%S"), "routes": []}

    for r in ROUTES:
        # travel = "(所要時間:15分)" if r["type"] == "train" else "(所要時間:10分)" # この行は削除またはコメントアウト
        # label = f"{r['label']} {travel}" # この行は削除またはコメントアウト
        # label は ROUTES で定義されたものをそのまま使うか、所要時間を動的に表示するなら別途考慮
        ent = {"label": r['label']} # travel情報を削除
        mp = {}

        for d in r.get("directions", []):
            if r["type"] == "train":
                lst = fetch_train_schedule(r["line_code"], d["dest_tag"])
            elif r["type"] == "bus_csv":
                lst = fetch_bus_schedule_csv(r["type"], d["dest_tag"])
            else:
                sh  = sheet_name(r["type"], d.get("sheet_direction"))
                lst = fetch_bus_schedule(sh, d["column"], r["file"])

            # --- ここから修正: 今から早い順に並べてmax件だけ表示 ---
            filtered = []
            for item in lst:
                if isinstance(item, dict):
                    current_time_str = item["time"]
                elif isinstance(item, str):
                    current_time_str = item
                else:
                    continue
                rm = remaining(current_time_str)
                if not (0 < rm.total_seconds() < 86400):
                    continue
                mins = int(rm.total_seconds() // 60)
                if mins < r["run"]:
                    continue
                filtered.append((rm, item, mins, current_time_str))
            # 残り時間の昇順でソート
            filtered.sort(key=lambda x: x[0])
            show, cnt = [], 0
            for tup in filtered:
                if cnt >= r["max"]:
                    break
                _, item, mins, current_time_str = tup
                adv = "歩けば間に合います" if mins >= r["walk"] else "走れば間に合います"
                display_parts = [f"{current_time_str}発"]
                if isinstance(item, dict):
                    train_type = item.get("type", "").strip()
                    destination = item.get("dest", "").strip()
                    if train_type and train_type not in ["-", "ー"]:
                        display_parts.append(f"【{train_type}】")
                    if destination and destination not in ["-", "ー"]:
                        display_parts.append(f"{destination}行")
                display_parts.append(f"- {mins}分 {adv}")
                show.append(f"{labs[cnt]}: {' '.join(display_parts)}")
                cnt += 1
            mp[d["column"]] = show
        ent["schedules"] = mp
        res["routes"].append(ent)

    return jsonify(res)

# ──────────────────────────────────────────
#  API: 天気情報
# ──────────────────────────────────────────
W_URL = "https://weather.tsukumijima.net/api/forecast/city/130010"


def get_weather() -> dict:
    try:
        return requests.get(W_URL, timeout=6).json()
    except Exception as e:
        print("Weather error:", e)
        return {}


@app.route("/api/weather")
def api_weather():
    return jsonify(get_weather())

# ──────────────────────────────────────────
#  API: ニュース
# ──────────────────────────────────────────
NHK = "https://www3.nhk.or.jp/rss/news/cat0.xml"
GGL = "https://news.google.com/rss/search?q=東急&hl=ja&gl=JP&ceid=JP:ja"


def get_news() -> list[str]:
    out, seen = [], set()
    for url in (NHK, GGL):
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                t = html.unescape(e.title)
                if t not in seen:
                    out.append(t)
                    seen.add(t)
                if len(out) >= 10:
                    break
        except Exception:
            pass
    return out


@app.route("/api/news")
def api_news():
    return jsonify({"news": get_news()})

# ──────────────────────────────────────────
#  API: 運行情報 (Tokyu + ODPT)
# ──────────────────────────────────────────
TOKYU_URL = "https://www.tokyu.co.jp/unten2/unten.html"

ODPT_API_KEY = os.getenv("ODPT_API_KEY", "")
ODPT_API_KEY_MAIN = os.getenv("ODPT_API_KEY_MAIN", ODPT_API_KEY)
ODPT_API_KEY_CHALLENGE = os.getenv("ODPT_API_KEY_CHALLENGE", ODPT_API_KEY)
ODPT_ENDPOINT_MAIN = os.getenv("ODPT_ENDPOINT_MAIN", "https://api.odpt.org/api/v4")
ODPT_ENDPOINT_CHALLENGE = os.getenv("ODPT_ENDPOINT_CHALLENGE", "https://api-challenge.odpt.org/api/v4")

if not ODPT_API_KEY_MAIN or not ODPT_API_KEY_CHALLENGE:
    logging.warning("ODPT API keys are not fully configured. Set ODPT_API_KEY_MAIN and ODPT_API_KEY_CHALLENGE.")

OPS = {
    "東京メトロ":       "odpt.Operator:TokyoMetro",
    "都営地下鉄":     "odpt.Operator:Toei",
    "横浜市交通局":   "odpt.Operator:YokohamaMunicipal",
    "多摩モノレール": "odpt.Operator:TamaMonorail",
    "JR東日本":       "odpt.Operator:JR-East",
    "東急電鉄":       "odpt.Operator:Tokyu",
    "東武鉄道":       "odpt.Operator:TobuRailway",
}

# 都営地下鉄 GTFS リアルタイム（列車遅延アラート用）
TOEI_ALERT_ENDPOINT    = f"{ODPT_ENDPOINT_MAIN}/gtfs/realtime/toei_odpt_train_alert"

# ── 各路線アイコンマップ ───────────────────────────────────────────
ICON_MAP = {
    # 東急電鉄
    "Toyoko":            "tokyurailway/icon_TY.png",
    "DenEnToshi":        "tokyurailway/icon_DT.png",
    "Ikegami":           "tokyurailway/icon_IK.png",
    "Meguro":            "tokyurailway/icon_MG.png",
    "Oimachi":           "tokyurailway/icon_OM.png",
    "Setagaya":          "tokyurailway/icon_SG.png",
    "TokyuTamagawa":     "tokyurailway/icon_TM.png",
    "Kodomonokuni":      "tokyurailway/icon_KD.png",
    "TokyuShinYokohama": "tokyurailway/icon_SH.png",
    # 東京メトロ
    "Chiyoda":           "tokyometro/icon_chiyoda.png",
    "Fukutoshin":        "tokyometro/icon_fukutoshin.png",
    "Ginza":             "tokyometro/icon_ginza.png",
    "Hanzomon":          "tokyometro/icon_hanzomon.png",
    "Hibiya":            "tokyometro/icon_hibiya.png",
    "Marunouchi":        "tokyometro/icon_marunouchi.png",
    "Namboku":           "tokyometro/icon_namboku.png",
    "Tozai":             "tokyometro/icon_tozai.png",
    "Yurakucho":         "tokyometro/icon_yurakucho.png",
    # 都営地下鉄
    "Oedo":              "toei/icon_oedo.png",
    "Asakusa":           "toei/icon_asakusa.png",
    "Mita":              "toei/icon_mita.png",
    "Shinjuku":          "toei/icon_shinjuku.png",
    "Arakawa":           "toei/icon_arakawa.png",
    # 横浜市営地下鉄
    "Blue":              "yokohama/icon_blue.png",
    "Green":             "yokohama/icon_green.png",
    # 東武鉄道
    "Tojo":              "tobu/icon_tojo.png",
    "Isesaki":           "tobu/icon_isesaki.png",
    "TobuSkytree":       "tobu/icon_skytree.png",
    "Nikko":             "tobu/icon_nikko.png",
    "TobuUrbanPark":     "tobu/icon_urbanpark.png",
    # JR東日本
    "Yamanote":          "JR/icon_JY.png",
    "KeihinTohokuNegishi": "JR/icon_JK.png",
    "Tokaido":           "JR/icon_JT.png",
    "ChuoRapid":         "JR/icon_JC.png",
    "ChuoSobuLocal":     "JR/icon_JB.png",
    "Yokosuka":          "JR/icon_JO.png",
    "SobuRapid":         "JR/icon_JO.png",
    "ShonanShinjuku":    "JR/icon_JS.png",
    "Utsunomiya":        "JR/icon_JU.png",
    "Takasaki":          "JR/icon_JU.png",
    "Keiyo":             "JR/icon_JE.png",
    "Musashino":         "JR/icon_JM.png",
    "Yokohama":          "JR/icon_JH.png",
    "JobanRapid":        "JR/icon_JJ.png",
    "JobanLocal":        "JR/icon_JL.png",
    # 多摩モノレール
    "TamaMonorail":      "icon_tamamonorail.png",
}

RAIL_NAME_MAP = {
    "Fukutoshin": "副都心線", "Namboku": "南北線", "Hanzomon": "半蔵門線",
    "Yurakucho": "有楽町線", "Chiyoda": "千代田線", "Tozai": "東西線",
    "Hibiya": "日比谷線", "Marunouchi": "丸の内線", "MarunouchiBranch": "丸の内線方南町支線",
    "Ginza": "銀座線", "Asakusa": "浅草線", "Mita": "三田線", "Shinjuku": "新宿線",
    "Oedo": "大江戸線", "Arakawa": "都電荒川線（東京さくらトラム）", "NipporiToneri": "日暮里舎人ライナー",
    "TamaMonorail": "多摩モノレール", "Rinkai": "りんかい線", "TsukubaExpress": "つくばエクスプレス線",
    "Green": "横浜市営地下鉄・グリーンライン", "Blue": "横浜市営地下鉄・ブルーライン",
    # — 東急電鉄 —
    "Toyoko":        "東横線", "Meguro":        "目黒線", "TokyuShinYokohama":"東急新横浜線",
    "DenEnToshi":    "田園都市線", "Oimachi":       "大井町線", "Ikegami":       "池上線",
    "TokyuTamagawa": "東急多摩川線", "Setagaya":      "世田谷線", "Kodomonokuni":  "こどもの国線",
    # — 東武鉄道 —
    "Tojo":              "東上線",
    "Ogose":             "越生線",
    "Isesaki":           "伊勢崎線",
    "TobuSkytree":       "スカイツリーライン",
    "TobuSkytreeBranch": "スカイツリーライン(押上-曳舟)",
    "Kameido":           "亀戸線",
    "Daishi":            "大師線",
    "Sano":              "佐野線",
    "Kiryu":             "桐生線",
    "Koizumi":           "小泉線",
    "KoizumiBranch":     "小泉線(支線)",
    "Nikko":             "日光線",
    "Utsunomiya":        "宇都宮線", # JRの同名路線と区別される (Operatorが違うため)
    "Kinugawa":          "鬼怒川線",
    "TobuUrbanPark":     "アーバンパークライン",
    # — JR東日本 —
    "Yamanote":          "山手線",
    "KeihinTohokuNegishi": "京浜東北・根岸線",
    "Tokaido":           "東海道線",
    "ChuoRapid":         "中央線快速",
    "ChuoSobuLocal":     "中央・総武線各駅停車",
    "Yokosuka":          "横須賀線",
    "SobuRapid":         "総武快速線",
    "ShonanShinjuku":    "湘南新宿ライン",
    "Utsunomiya":        "宇都宮線",
    "Takasaki":          "高崎線",
    "Keiyo":             "京葉線",
    "Musashino":         "武蔵野線",
    "Yokohama":          "横浜線",
    "JobanRapid":        "常磐線快速",
    "JobanLocal":        "常磐線各駅停車",
}

# ── 東急電鉄運行情報取得 ─────────────────────────
def fetch_tokyu_traininfo() -> list[dict[str, str]]:
    """
    東急電鉄の運行情報のみを ODPT API から取得して返す。
    API失敗時はHTMLスクレイピングにフォールバック。
    """
    if not ODPT_API_KEY_CHALLENGE:
        logging.warning("ODPT_API_KEY_CHALLENGE is missing; falling back to HTML scraping.")
        return fetch_tokyu_htmlinfo()

    url = (
        f"{ODPT_ENDPOINT_CHALLENGE}/odpt:TrainInformation"
        f"?odpt:operator=odpt.Operator:Tokyu"
        f"&acl:consumerKey={ODPT_API_KEY_CHALLENGE}"
    )
    try:
        res = requests.get(url, timeout=6)
        logging.info(f"TrainInformation API status: {res.status_code} for URL: {url}")
        res.raise_for_status()
        data = res.json()
        if not data:
            logging.warning("API returned empty data. Falling back to HTML scraping.")
            return fetch_tokyu_htmlinfo()
    except Exception as e:
        logging.error(f"API request failed: {e}. Falling back to HTML scraping.")
        return fetch_tokyu_htmlinfo()

    out: list[dict[str, str]] = []
    for item in data:
        raw = item.get("odpt:railway", "")
        if not raw: continue
        rc  = raw.split('.')[-1]
        line_ja = RAIL_NAME_MAP.get(rc, rc)
        txt = item.get("odpt:trainInformationText", {}).get("ja", "情報なし")
        icon_path = ICON_MAP.get(rc)  # url_for を使わず、パスを直接取得
        out.append({
            "line":   line_ja,
            "status": txt,
            "logo":   icon_path,  # ここではパスを返す
            "rc":     rc
        })
    return out

# --- HTMLスクレイピングによる東急運行情報取得 ---
def fetch_tokyu_htmlinfo() -> list[dict[str, str]]:
    """
    東急公式サイトをスクレイピングして運行情報を取得します。
    (APIが失敗した際の予備手段)
    """
    try:
        res = requests.get(TOKYU_URL, timeout=6)
        res.raise_for_status()
    except Exception as e:
        logging.error(f"HTML fetch failed: {e}")
        return []

    soup = BeautifulSoup(res.text, 'html.parser')
    result = []
    for item in soup.select('.unten_info-body-item'):
        line   = item.select_one('.line-name')
        status = item.select_one('.unten_info-status-text')
        img    = item.select_one('img')
        if not line or not status: continue
        line_text = line.get_text(strip=True)
        status_text = status.get_text(strip=True)
        logo_path = None  # logo_url から logo_path に変更
        if img and img.has_attr('src'):
            img_filename = Path(img['src']).name
            icon_key = img_filename.replace('.png', '').split('_')[-1]
            found_icon = None
            for key, val in ICON_MAP.items():
                if icon_key.lower() in val.lower():
                    found_icon = val
                    break
            if found_icon:
                logo_path = found_icon # パスをそのまま格納
        result.append({'line': line_text, 'status': status_text, 'logo': logo_path})
    logging.info(f"HTML scraping found {len(result)} records.")
    return result


def _status_db_connection() -> sqlite3.Connection:
    STATUS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STATUS_DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def ensure_status_cache_schema() -> None:
    with _status_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS odpt_status_snapshot (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                total_count INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS odpt_status_items (
                group_order INTEGER NOT NULL,
                operator_order INTEGER NOT NULL,
                item_order INTEGER NOT NULL,
                operator_label TEXT NOT NULL,
                line_code TEXT NOT NULL,
                line_label TEXT NOT NULL,
                status_text TEXT NOT NULL,
                display_text TEXT NOT NULL,
                logo_path TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_odpt_status_items_sort
            ON odpt_status_items(group_order, operator_order, item_order)
            """
        )


def save_status_snapshot(rows: list[dict[str, object]], updated_at: str, source: str) -> None:
    ensure_status_cache_schema()
    with _status_db_connection() as connection:
        connection.execute("DELETE FROM odpt_status_items")
        connection.execute("DELETE FROM odpt_status_snapshot WHERE id = 1")
        connection.execute(
            "INSERT INTO odpt_status_snapshot (id, updated_at, source, total_count) VALUES (1, ?, ?, ?)",
            (updated_at, source, len(rows)),
        )
        connection.executemany(
            """
            INSERT INTO odpt_status_items (
                group_order,
                operator_order,
                item_order,
                operator_label,
                line_code,
                line_label,
                status_text,
                display_text,
                logo_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    int(row["group_order"]),
                    int(row["operator_order"]),
                    int(row["item_order"]),
                    str(row["operator_label"]),
                    str(row["line_code"]),
                    str(row["line_label"]),
                    str(row["status_text"]),
                    str(row["display_text"]),
                    row.get("logo_path"),
                )
                for row in rows
            ],
        )


def load_status_snapshot() -> dict[str, object] | None:
    if not STATUS_DB_PATH.exists():
        return None

    try:
        ensure_status_cache_schema()
        with _status_db_connection() as connection:
            meta = connection.execute(
                "SELECT updated_at, source, total_count FROM odpt_status_snapshot WHERE id = 1"
            ).fetchone()
            if not meta:
                return None

            rows = connection.execute(
                """
                SELECT
                    group_order,
                    operator_order,
                    item_order,
                    operator_label,
                    line_code,
                    line_label,
                    status_text,
                    display_text,
                    logo_path
                FROM odpt_status_items
                ORDER BY group_order ASC, operator_order ASC, item_order ASC
                """
            ).fetchall()

            if not rows:
                return None

            return {
                "updated_at": meta["updated_at"],
                "source": meta["source"],
                "total_count": int(meta["total_count"]),
                "rows": [dict(row) for row in rows],
            }
    except Exception as e:
        logging.warning(f"status cache load failed: {e}")
        return None


def build_status_rows_live() -> tuple[list[dict[str, object]], str]:
    rows: list[dict[str, object]] = []
    snapshot_at = datetime.now().isoformat(timespec="seconds")

    for operator_order, label in enumerate(TRAIN_INFO_DISPLAY_ORDER):
        op_code = OPS.get(label)
        if not op_code:
            continue

        try:
            all_infos: list[dict[str, str]] = []
            if label == "東急電鉄":
                all_infos = fetch_tokyu_traininfo()
                if any(info.get("rc") for info in all_infos):
                    all_infos = [info for info in all_infos if info.get("rc") in RAIL_NAME_MAP]
            elif label in ("JR東日本", "東武鉄道"):
                all_infos = fetch_odpt_traininfo(op_code, ODPT_ENDPOINT_CHALLENGE, ODPT_API_KEY_CHALLENGE)
                all_infos = [info for info in all_infos if info.get("rc") in RAIL_NAME_MAP]
            else:
                all_infos = fetch_odpt_traininfo(op_code, ODPT_ENDPOINT_MAIN, ODPT_API_KEY_MAIN)
                all_infos = [info for info in all_infos if info.get("rc") in RAIL_NAME_MAP]

            for item_order, ent in enumerate(all_infos):
                line_label = str(ent.get("line", "")).strip()
                status_text = str(ent.get("status", "情報なし")).strip() or "情報なし"
                display_text = f"{label} {line_label}: {status_text}" if line_label else f"{label}: {status_text}"
                rows.append({
                    "group_order": 0 if "平常" not in status_text else 1,
                    "operator_order": operator_order,
                    "item_order": item_order,
                    "operator_label": label,
                    "line_code": str(ent.get("rc", "")),
                    "line_label": line_label,
                    "status_text": status_text,
                    "display_text": display_text,
                    "logo_path": ent.get("logo"),
                })
        except Exception as e:
            logging.error(f"{label}の情報取得でエラー: {e}")

    rows.sort(key=lambda row: (row["group_order"], row["operator_order"], row["item_order"]))
    return rows, snapshot_at


def format_status_response(rows: list[dict[str, object]], page: int, page_size: int, updated_at: str, source: str) -> dict[str, object]:
    total_count = len(rows)
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    if total_pages and page >= total_pages:
        page = total_pages - 1
    start = page * page_size
    page_rows = rows[start:start + page_size]
    return {
        "status": [
            {
                "logo": row.get("logo_path"),
                "text": row.get("display_text"),
            }
            for row in page_rows
        ],
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "updated_at": updated_at,
        "source": source,
    }


def start_odpt_poller_process() -> None:
    global ODPT_POLLER_PROCESS

    if not STATUS_POLLER_AUTO_START:
        logging.info("ODPT poller auto-start is disabled.")
        return

    candidate_paths = [STATUS_POLLER_EXECUTABLE]
    alternate_path = BASE_DIR / "rust" / "odpt_poller" / "target" / "x86_64-pc-windows-gnu" / "release" / ("odpt_poller.exe" if os.name == "nt" else "odpt_poller")
    if alternate_path not in candidate_paths:
        candidate_paths.append(alternate_path)

    executable_path = next((path for path in candidate_paths if path.exists()), None)
    if executable_path is None:
        logging.info(f"ODPT poller executable not found: {STATUS_POLLER_EXECUTABLE}")
        return

    if ODPT_POLLER_PROCESS is not None and ODPT_POLLER_PROCESS.poll() is None:
        return

    try:
        ODPT_POLLER_PROCESS = subprocess.Popen(
            [
                str(executable_path),
                "--db",
                str(STATUS_DB_PATH),
                "--interval-seconds",
                str(max(STATUS_POLLER_INTERVAL_SECONDS, 60)),
            ],
            cwd=str(BASE_DIR),
        )
        logging.info(f"Started ODPT poller: {executable_path}")
        atexit.register(stop_odpt_poller_process)
    except Exception as e:
        logging.error(f"Failed to start ODPT poller: {e}")


def stop_odpt_poller_process() -> None:
    global ODPT_POLLER_PROCESS

    if ODPT_POLLER_PROCESS is None:
        return

    try:
        if ODPT_POLLER_PROCESS.poll() is None:
            ODPT_POLLER_PROCESS.terminate()
    except Exception:
        pass
    finally:
        ODPT_POLLER_PROCESS = None

# ── 汎用 ODPT 運行情報取得関数 ─────────────────────────
def fetch_odpt_traininfo(operator_code: str, endpoint: str, api_key: str) -> list[dict[str, str]]:
    """
    任意の事業者の運行情報を ODPT API から取得し、
    [{ 'line': 路線名, 'status': 運行状況, 'logo': ロゴURL, 'rc': 路線コード }] のリストで返す。
    """
    url = (
        f"{endpoint}/odpt:TrainInformation"
        f"?odpt:operator={operator_code}"
        f"&acl:consumerKey={api_key}"
    )
    if not api_key:
        logging.warning(f"ODPT API key is missing for {operator_code}.")
        return []
    try:
        res = requests.get(url, timeout=6)
        logging.info(f"ODPT TrainInformation API status: {res.status_code} for {operator_code}")
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        logging.error(f"ODPT API request failed for {operator_code}: {e}")
        return []

    out: list[dict[str, str]] = []
    for item in data:
        raw = item.get("odpt:railway", "")
        if not raw:
            continue
        rc = raw.split(".")[-1]
        line_ja = RAIL_NAME_MAP.get(rc, rc)
        txt = item.get("odpt:trainInformationText", {}).get("ja", "情報なし")
        icon_path = ICON_MAP.get(rc) # url_for を使わず、パスを直接取得
        out.append({
            "line": line_ja,
            "status": txt,
            "logo": icon_path, # ここではパスを返す
            "rc": rc
        })
    return out

# ──────────────────────────────────────────
#  API: 運行情報 (設定)
# ──────────────────────────────────────────
# 表示する運行情報の最大行数
# MAX_STATUS_LINES = 15  # この行は不要なので削除

# 運行情報を表示する事業者の順序
TRAIN_INFO_DISPLAY_ORDER = [
    "東急電鉄",
    "JR東日本",
    "東京メトロ",
    "都営地下鉄",
    "横浜市交通局",
    "東武鉄道",
    "多摩モノレール",
]

# ──────────────────────────────────────────
#  API: 運行情報 (Tokyu + ODPT)
# ──────────────────────────────────────────
@app.route("/api/status")
def api_status():
    """
    複数事業者の運行情報を路線ごとに返却します。
    異常情報を優先してリストの先頭に配置します。
    """
    try:
        page_size = int(request.args.get('page_size', request.args.get('max_lines', 2)))
    except (ValueError, TypeError):
        page_size = 2
    try:
        page = int(request.args.get('page', 0))
    except (ValueError, TypeError):
        page = 0

    if page_size < 1:
        page_size = 1
    if page < 0:
        page = 0

    cached_snapshot = load_status_snapshot()
    if cached_snapshot:
        return jsonify(format_status_response(
            cached_snapshot["rows"],
            page,
            page_size,
            str(cached_snapshot["updated_at"]),
            str(cached_snapshot["source"]),
        ))

    live_rows, updated_at = build_status_rows_live()
    if live_rows:
        try:
            save_status_snapshot(live_rows, updated_at, "live")
        except Exception as e:
            logging.warning(f"failed to persist live status snapshot: {e}")

    return jsonify(format_status_response(live_rows, page, page_size, updated_at, "live" if live_rows else "unavailable"))

# ──────────────────────────────────────────
#  ルート
# ──────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", page=1)


@app.route("/page/<int:p>")
def index_page(p: int):
    return render_template("index.html", page=p)

# ──────────────────────────────────────────
#  API CHECK & UTILITIES (MOVED HERE)
# ──────────────────────────────────────────
def get_line_logos(operator_code: str) -> list[dict[str, str]]:
    """
    指定事業者の路線ロゴ(systemMap)一覧を取得し、
    [{ 'railway': 路線コード, 'logo': ロゴURL }] のリストで返す。
    """
    url = (
        f"{ODPT_ENDPOINT_MAIN}/odpt:Railway"
        f"?odpt:operator={operator_code}"
        f"&acl:consumerKey={ODPT_API_KEY_MAIN}"
    )
    try:
        res = requests.get(url, timeout=6)
        logging.info(f"Railway Logos API status: {res.status_code}")
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        logging.error(f"Railway Logos API request failed: {e}")
        return []
    out = []
    for it in data:
        raw = it.get("odpt:railway", "")
        rc1 = raw.split(":")[-1]
        rc  = rc1.split(".")[-1]
        logo = it.get("odpt:systemMap")
        out.append({"railway": rc, "logo": logo})
    return out

def check_apis():
    """
    アプリ起動時に各 ODPT API の疎通をチェックし、
    ターミナルに結果を出力する。
    """
    apis = {
        "Tokyu TrainInformation": lambda: fetch_tokyu_traininfo(),
        "Tokyu Railway Logos":    lambda: get_line_logos("odpt.Operator:Tokyu"),
    }

    for name, func in apis.items():
        try:
            result = func()
            count = len(result) if isinstance(result, (list, dict)) else "?"
            logging.info(f"{name}: OK (件数={count})")
        except Exception as e:
            logging.error(f"{name}: ERROR ({e})")

# ──────────────────────────────────────────
def ensure_csv_encoding():
    """CSVファイルのエンコーディングを確認・修正"""
    # ブルーラインCSV
    bl_files = [
        f"timetable_BL_{day}_{dest}.csv" 
        for day in ["weekday", "holiday"] 
        for dest in ["Azamino", "Shonandai"]
    ]
    
    # 東急バスCSV
    bus_files = [
        f"timetable_BUS_{day}_{dest}.csv"
        for day in ["weekday", "holiday", "saturday"]
        for dest in ["Saginuma", "CenterKita"]
    ]
    
    # 全てのCSVをチェック
    for file_list, file_type in [(bl_files, "ブルーライン"), (bus_files, "東急バス")]:
        for filename in file_list:
            csv_path = DATA_DIR / filename
            if not csv_path.exists():
                print(f"[WARNING] {file_type}時刻表ファイルが見つかりません: {filename}")
                continue
                
            try:
                # ファイルをcp932で読み込んでエンコーディングを確認
                with open(csv_path, 'r', encoding='cp932') as f:
                    content = f.read()
                print(f"[INFO] {file_type}時刻表確認: {filename} (OK)")
            except Exception as e:
                print(f"[ERROR] {file_type}時刻表エンコーディングチェック失敗: {filename} - {e}")

# アプリケーション起動前に実行
if __name__ == "__main__":

    if STATUS_STARTUP_CHECKS:
        with app.app_context():
            check_apis()
    else:
        logging.info("Skipping ODPT startup checks; the Rust poller owns cache refresh.")
    # サーバ起動前にCSVエンコーディング確認
    ensure_csv_encoding()
    # Rust poller はビルド済みバイナリがある場合のみ自動起動する
    start_odpt_poller_process()

    def open_browser():
        """
        デフォルトのウェブブラウザでFlaskアプリケーションのURLを開きます。
        """
        webbrowser.open_new("http://127.0.0.1:5000")

    def create_gui():
        """
        シンプルなTkinterウィンドウを作成し、ブラウザを開くためのボタンを配置します。
        """
        # Tkinterのルートウィンドウを作成
        root = tk.Tk()  # type: ignore
        root.title("発車案内")
        root.geometry("300x100")

        label = tk.Label(root, text="下のボタンをクリックして発車案内を表示します。")  # type: ignore
        label.pack(pady=10)

        button = tk.Button(root, text="発車案内を表示する", command=open_browser)  # type: ignore
        button.pack(pady=10)

        # 作成者情報ラベル（右下配置）
        author_label = tk.Label(root, text="作成者:刘承洋 g2213164@tcu.ac.jp", anchor="se", fg="gray")  # type: ignore
        author_label.place(relx=1.0, rely=1.0, anchor="se", x=-5, y=-5)

        root.mainloop()  # type: ignore    # Flaskサーバーを別スレッドで実行
    flask_thread = threading.Thread(target=lambda: app.run(debug=True, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()

    # Tkinter GUIをメインスレッドで実行
    create_gui()

# （tweets by tokyu official 関連のコード・記述はありませんでした）
