# Tokyu Departure Board WebApp

## 概要
東急・東京メトロ・都営地下鉄・横浜市営地下鉄・JR東日本・東武鉄道など複数事業者の電車・バス時刻表と運行情報を提供するWebアプリです。

- 発車案内（CSV/Excel対応）
- 天気情報（つくみじまAPI）
- ニュース（NHK/Google News）
- 運行情報（Tokyu公式＋ODPT API、主要事業者対応）

## 主な機能

### 1. 発車案内
- `timetable_data/` 配下のCSV/Excelから時刻表を読み込み、駅・バス停ごとに直近の発車時刻を表示。
- 電車・バスともに複数方面対応。
- **2025-08-02以降の仕様:**
    - 「1時間以内」→「24時間以内」の便を表示するように拡大。
    - バス時刻表（Excel）はシート名・列名のミスマッチをデバッグ出力で確認可能。
    - ROUTES定義の`sheet_direction`や`column`は、実際のExcelシート名・列名に合わせて調整してください。

### 2. 運行情報API `/api/status`
#### 概要
- 複数事業者（東急・東京メトロ・都営地下鉄・横浜市交・JR東日本・東武鉄道）の運行情報をまとめて取得し、異常時のみ詳細を表示。全て平常時は「平常運転」と事業者ごとに表示。
- レスポンスは `{"status": [...]}` 形式の配列で、フロントエンド（`static/app.js`）と連携。

#### 取得ロジック
- **東急電鉄**: ODPT API（チャレンジAPI）で取得。API失敗時は公式サイトHTMLを自動スクレイピングしてフォールバック。
- **JR東日本・東武鉄道**: ODPTチャレンジAPIを利用。
- **東京メトロ・都営地下鉄・横浜市交・多摩モノレール**: ODPTメインAPIを利用。
- **Toei GTFS-RT（リアルタイム遅延アラート）ロジックは完全削除済み。**

#### レスポンス例
```json
{
  "status": [
    {"logo": "/static/img/icon_TY.png", "text": "東急電鉄 東横線: 遅延が発生しています"},
    {"logo": null, "text": "東京メトロ: 平常運転"},
    ...
  ]
}
```
- 各要素は事業者ごとに異常時は詳細、平常時は「平常運転」を返します。
- ロゴ画像は一部路線のみ対応。

### 3. 天気・ニュースAPI
- `/api/weather`：つくみじま天気API（東京都心）
- `/api/news`：NHK・Google Newsから最大10件取得

## ディレクトリ構成

```
app_20250808_remote/
├── README.md                # このドキュメント
├── timetable_app.py         # Flask本体・APIロジック
├── memo.txt                 # メモ等
├── static/                  # フロントエンド関連
│   ├── app.js               # メインJS
│   ├── style.css            # スタイルシート
│   └── img/                 # 路線アイコン等画像
│       ├── ...（各路線・バスのアイコン画像、サブディレクトリ含む）
├── templates/               # HTMLテンプレート
│   └── index.html
├── timetable_data/          # 時刻表データ（CSV/Excel）
│   ├── ...（各路線・バス停・曜日ごとの時刻表CSV/Excel）
```

- `static/img/` 配下には各路線・バスのアイコン画像が格納されています（サブディレクトリ含む。JR東日本・東急・メトロ・都営・横浜・東武など）。
- `timetable_data/` 配下には各路線・バス停・曜日ごとの時刻表CSV/Excelが格納されています。
- その他、必要に応じてファイルを追加してください。

## 注意事項
- ODPT APIキーはソース内で明示的に分離管理されています。
- 東急運行情報はAPI障害時もHTMLフォールバックで高可用性。
- Toei GTFS-RT（リアルタイム遅延アラート）は2025年7月時点で未対応です。
- **バス時刻表（Excel）はシート名・列名のミスマッチに注意。サーバログのデバッグ出力を参考にROUTES定義を調整してください。**

## 起動方法
1. 必要なPythonパッケージをインストール
   - `pip install flask pandas requests beautifulsoup4 feedparser openpyxl`
2. `timetable_data/`に必要なCSV/Excelを配置
3. サーバ起動
   - `python timetable_app.py`

## ライセンス
MIT License

---
2025-08-02 仕様・デバッグ方法追記

