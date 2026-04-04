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
    - ODPT APIキーは環境変数 `ODPT_API_KEY_MAIN` / `ODPT_API_KEY_CHALLENGE` で設定してください。

### 2. 運行情報API `/api/status`
#### 概要
- 複数事業者（東急・東京メトロ・都営地下鉄・横浜市交・JR東日本・東武鉄道）の運行情報をまとめて取得し、異常時のみ詳細を表示。全て平常時は「平常運転」と事業者ごとに表示。
- ODPT 生データは Rust のポーラーが 5 分または 10 分間隔で SQLite キャッシュに保存し、Flask はそのキャッシュを高速に読み出します。
- レスポンスは `{"status": [...]}` 形式の配列で、フロントエンド（`static/app.js`）と連携。`updated_at` と `source` も返し、カード下部に更新時刻を表示します。

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
- ODPT APIキーは環境変数で管理してください。
- 東急運行情報はAPI障害時もHTMLフォールバックで高可用性。
- Toei GTFS-RT（リアルタイム遅延アラート）は2025年7月時点で未対応です。
- **バス時刻表（Excel）はシート名・列名のミスマッチに注意。サーバログのデバッグ出力を参考にROUTES定義を調整してください。**

## 起動方法
1. 必要なPythonパッケージをインストール
   - `pip install flask pandas requests beautifulsoup4 feedparser openpyxl`
2. Rust toolchain をインストール
  - `winget install -e --id Rustlang.Rustup`
  - `cargo` 実行時は `C:\msys64\mingw64\bin` を PATH に含めるか、MSYS2 MinGW x64 シェルを使ってください。
3. ODPT APIキーを環境変数に設定
  - `ODPT_API_KEY_MAIN`
  - `ODPT_API_KEY_CHALLENGE`
4. 必要ならポーラー間隔を設定
  - `ODPT_POLL_INTERVAL_SECONDS=300` で 5 分
  - `ODPT_POLL_INTERVAL_SECONDS=600` で 10 分
5. `rust/odpt_poller` でビルド
  - `cargo build --release`
  - 出力は `rust/odpt_poller/target/x86_64-pc-windows-gnu/release/odpt_poller.exe` です。
6. `timetable_data/`に必要なCSV/Excelを配置
7. サーバ起動
  - `python timetable_app.py`

### ODPT ポーラー
- Flask は `ODPT_POLLER_EXECUTABLE` に指定した Rust バイナリが存在する場合、自動で起動します。
- 既定の DB は `runtime/odpt_status.db` です。
- 自動起動を止めたい場合は `ODPT_POLLER_AUTO_START=0` を設定してください。

## ライセンス
MIT License

---
2025-08-02 仕様・デバッグ方法追記

