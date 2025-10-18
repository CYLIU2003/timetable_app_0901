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

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
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
# ★★★ 変更点 1: 正しいAPIキーを設定 ★★★
CHALLENGE_API_KEY = "t2fgb24cy400zu6dq33v6otyoinj7y16izqtfdufh5i43wkzv0gsbkebx79v6h7r" 

OPS = {
    "東京メトロ":       "odpt.Operator:TokyoMetro",
    "都営地下鉄":     "odpt.Operator:Toei",
    "横浜市交通局":   "odpt.Operator:YokohamaMunicipal",
    "多摩モノレール": "odpt.Operator:TamaMonorail",
    "JR東日本":       "odpt.Operator:JR-East",
    "東急電鉄":       "odpt.Operator:Tokyu",
    "東武鉄道":       "odpt.Operator:TobuRailway",
}

# ★★★ 変更点 2: 正しいAPIエンドポイントを設定 ★★★
ODPT_ENDPOINT = "https://api-challenge.odpt.org/api/v4"
API_KEY = CHALLENGE_API_KEY

# ── ODPT API キー ───────────────────────────────────────────
# 東京メトロ・都営・横浜市交用（通常エンドポイント）
API_KEY_MAIN           = "841qfdgzgywu5oktxrzqst5mosl5apeis3r5bz98aorxk8175pr1e7zd2k4pywqh"
ENDPOINT_MAIN          = "https://api.odpt.org/api/v4"

# JR東日本・東急・東武用（チャレンジエンドポイント）
API_KEY_CHALLENGE      = "t2fgb24cy400zu6dq33v6otyoinj7y16izqtfdufh5i43wkzv0gsbkebx79v6h7r"
ENDPOINT_CHALLENGE     = "https://api-challenge.odpt.org/api/v4"

# 都営地下鉄 GTFS リアルタイム（列車遅延アラート用）
TOEI_ALERT_ENDPOINT    = f"{ENDPOINT_MAIN}/gtfs/realtime/toei_odpt_train_alert"

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
    url = (
        f"{ODPT_ENDPOINT}/odpt:TrainInformation"
        f"?odpt:operator=odpt.Operator:Tokyu"
        f"&acl:consumerKey={API_KEY}"
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
        max_lines = int(request.args.get('max_lines', 2))
    except (ValueError, TypeError):
        max_lines = 2

    abnormal_list = []
    normal_list = []

    # 指定された順序で全事業者をループし、情報を収集・仕分けする
    for label in TRAIN_INFO_DISPLAY_ORDER:
        op_code = OPS.get(label)
        if not op_code:
            continue

        try:
            # 1. 事業者ごとに情報を取得
            all_infos = []
            if label in ("東急電鉄", "JR東日本", "東武鉄道"):
                if label == "東急電鉄":
                    all_infos = fetch_tokyu_traininfo()
                else:
                    all_infos = fetch_odpt_traininfo(op_code, ENDPOINT_CHALLENGE, API_KEY_CHALLENGE)
                # ★★★ 修正点: フィルタリング基準をアイコン有無から路線名定義の有無へ変更 ★★★
                # これにより、アイコンがなくても名前が定義されていれば表示対象になる
                all_infos = [info for info in all_infos if info.get("rc") in RAIL_NAME_MAP]
            else:
                all_infos = fetch_odpt_traininfo(op_code, ENDPOINT_MAIN, API_KEY_MAIN)
            
            # 2. 取得した情報を「異常」と「平常」に仕分ける
            for ent in all_infos:
                text = f"{label} {ent.get('line', '')}: {ent.get('status', '情報なし')}"
                item_data = {"logo": ent.get("logo"), "text": text}
                
                if "平常" not in ent.get("status", ""):
                    abnormal_list.append(item_data)
                else:
                    normal_list.append(item_data)

        except Exception as e:
            logging.error(f"{label}の情報取得でエラー: {e}")
            # エラーが発生した場合はリストに追加しないか、エラーメッセージを追加するか選択
            # ここではシンプルにするため、何もしない

    # 3. 異常リストと平常リストを結合し、指定された行数だけを返す
    final_status_list = abnormal_list + normal_list
    return jsonify({"status": final_status_list[:max_lines]})

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
        f"{ODPT_ENDPOINT}/odpt:Railway"
        f"?odpt:operator={operator_code}"
        f"&acl:consumerKey={API_KEY}"
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

    # 起動時 API チェック（アプリケーションコンテキスト内で実行）
    with app.app_context():
        check_apis()
    # サーバ起動前にCSVエンコーディング確認
    ensure_csv_encoding()

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
