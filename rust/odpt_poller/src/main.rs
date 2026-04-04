use anyhow::{anyhow, Context, Result};
use chrono::Utc;
use clap::Parser;
use reqwest::blocking::Client;
use rusqlite::{params, Connection};
use scraper::{Html, Selector};
use serde_json::Value;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

const TOKYU_URL: &str = "https://www.tokyu.co.jp/unten2/unten.html";
const ODPT_ENDPOINT_MAIN: &str = "https://api.odpt.org/api/v4";
const ODPT_ENDPOINT_CHALLENGE: &str = "https://api-challenge.odpt.org/api/v4";

const TRAIN_INFO_DISPLAY_ORDER: &[(&str, &str, FetchMode)] = &[
    ("東急電鉄", "odpt.Operator:Tokyu", FetchMode::Tokyu),
    ("JR東日本", "odpt.Operator:JR-East", FetchMode::Challenge),
    ("東京メトロ", "odpt.Operator:TokyoMetro", FetchMode::Main),
    ("都営地下鉄", "odpt.Operator:Toei", FetchMode::Main),
    ("横浜市交通局", "odpt.Operator:YokohamaMunicipal", FetchMode::Main),
    ("東武鉄道", "odpt.Operator:TobuRailway", FetchMode::Challenge),
    ("多摩モノレール", "odpt.Operator:TamaMonorail", FetchMode::Main),
];

#[derive(Clone, Copy, Debug)]
enum FetchMode {
    Main,
    Challenge,
    Tokyu,
}

#[derive(Parser, Debug)]
#[command(author, version, about = "ODPT status poller that writes a SQLite cache")]
struct Cli {
    #[arg(long, value_name = "PATH", default_value = "runtime/odpt_status.db")]
    db: PathBuf,

    #[arg(long, value_name = "SECONDS", default_value_t = 300)]
    interval_seconds: u64,

    #[arg(long)]
    once: bool,
}

#[derive(Clone, Debug)]
struct RawStatusRow {
    line_code: String,
    line_label: String,
    status_text: String,
    logo_path: Option<String>,
}

#[derive(Clone, Debug)]
struct StatusRow {
    group_order: i64,
    operator_order: i64,
    item_order: i64,
    operator_label: String,
    line_code: String,
    line_label: String,
    status_text: String,
    display_text: String,
    logo_path: Option<String>,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    if cli.once {
        run_once(&cli)?;
        return Ok(());
    }

    loop {
        match run_once(&cli) {
            Ok(summary) => {
                println!(
                    "[ODPT] cached {} rows at {}",
                    summary.total_count, summary.updated_at
                );
            }
            Err(err) => {
                eprintln!("[ODPT] poll failed: {err:#}");
            }
        }

        thread::sleep(Duration::from_secs(cli.interval_seconds.max(60)));
    }
}

struct SnapshotSummary {
    updated_at: String,
    total_count: usize,
}

fn run_once(cli: &Cli) -> Result<SnapshotSummary> {
    ensure_schema(&cli.db)?;

    let client = Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .context("failed to build HTTP client")?;

    let (rows, updated_at) = collect_status_rows(&client);
    if rows.is_empty() {
        return Err(anyhow!("no ODPT rows were collected"));
    }

    write_snapshot(&cli.db, &rows, &updated_at, "poller")?;

    Ok(SnapshotSummary {
        updated_at,
        total_count: rows.len(),
    })
}

fn collect_status_rows(client: &Client) -> (Vec<StatusRow>, String) {
    let mut rows: Vec<StatusRow> = Vec::new();
    let updated_at = Utc::now().to_rfc3339();

    for (operator_order, (operator_label, operator_code, mode)) in
        TRAIN_INFO_DISPLAY_ORDER.iter().enumerate()
    {
        let operator_label = *operator_label;
        let operator_code = *operator_code;
        let mode = *mode;

        let raw_rows = match mode {
            FetchMode::Tokyu => fetch_tokyu_traininfo(client),
            FetchMode::Challenge => {
                fetch_odpt_traininfo(client, operator_code, ODPT_ENDPOINT_CHALLENGE, &odpt_key(mode))
            }
            FetchMode::Main => {
                fetch_odpt_traininfo(client, operator_code, ODPT_ENDPOINT_MAIN, &odpt_key(mode))
            }
        };

        let filtered_rows = if matches!(mode, FetchMode::Tokyu) && raw_rows.iter().any(|row| !row.line_code.is_empty()) {
            raw_rows
                .into_iter()
                .filter(|row| line_code_to_label(&row.line_code).is_some())
                .collect::<Vec<_>>()
        } else if matches!(mode, FetchMode::Tokyu) {
            raw_rows
        } else {
            raw_rows
                .into_iter()
                .filter(|row| line_code_to_label(&row.line_code).is_some())
                .collect::<Vec<_>>()
        };

        for (item_order, raw) in filtered_rows.into_iter().enumerate() {
            let group_order = if raw.status_text.contains("平常") { 1 } else { 0 };
            let display_text = if raw.line_label.is_empty() {
                format!("{}: {}", operator_label, raw.status_text)
            } else {
                format!("{} {}: {}", operator_label, raw.line_label, raw.status_text)
            };

            rows.push(StatusRow {
                group_order,
                operator_order: operator_order as i64,
                item_order: item_order as i64,
                operator_label: operator_label.to_string(),
                line_code: raw.line_code,
                line_label: raw.line_label,
                status_text: raw.status_text,
                display_text,
                logo_path: raw.logo_path,
            });
        }
    }

    rows.sort_by(|left, right| {
        left.group_order
            .cmp(&right.group_order)
            .then(left.operator_order.cmp(&right.operator_order))
            .then(left.item_order.cmp(&right.item_order))
    });

    (rows, updated_at)
}

fn odpt_key(mode: FetchMode) -> String {
    match mode {
        FetchMode::Main => env::var("ODPT_API_KEY_MAIN").ok().or_else(|| env::var("ODPT_API_KEY").ok()).unwrap_or_default(),
        FetchMode::Challenge | FetchMode::Tokyu => env::var("ODPT_API_KEY_CHALLENGE").ok().or_else(|| env::var("ODPT_API_KEY").ok()).unwrap_or_default(),
    }
}

fn fetch_tokyu_traininfo(client: &Client) -> Vec<RawStatusRow> {
    let api_key = odpt_key(FetchMode::Tokyu);
    if api_key.is_empty() {
        eprintln!("[ODPT] missing ODPT_API_KEY_CHALLENGE; using Tokyu HTML fallback");
        return fetch_tokyu_htmlinfo(client);
    }

    let url = format!(
        "{}/odpt:TrainInformation?odpt:operator=odpt.Operator:Tokyu&acl:consumerKey={}",
        ODPT_ENDPOINT_CHALLENGE, api_key
    );

    match client.get(url).send() {
        Ok(response) if response.status().is_success() => match response.json::<Value>() {
            Ok(Value::Array(items)) if !items.is_empty() => items
                .iter()
                .filter_map(|item| build_row_from_odpt_item(item, "東急電鉄"))
                .collect(),
            Ok(_) => fetch_tokyu_htmlinfo(client),
            Err(err) => {
                eprintln!("[ODPT] Tokyu JSON parse failed: {err}");
                fetch_tokyu_htmlinfo(client)
            }
        },
        Ok(response) => {
            eprintln!("[ODPT] Tokyu API status {} -> HTML fallback", response.status());
            fetch_tokyu_htmlinfo(client)
        }
        Err(err) => {
            eprintln!("[ODPT] Tokyu API request failed: {err}; HTML fallback");
            fetch_tokyu_htmlinfo(client)
        }
    }
}

fn fetch_tokyu_htmlinfo(client: &Client) -> Vec<RawStatusRow> {
    let response = match client.get(TOKYU_URL).send() {
        Ok(response) if response.status().is_success() => response,
        Ok(response) => {
            eprintln!("[ODPT] Tokyu HTML status {}", response.status());
            return Vec::new();
        }
        Err(err) => {
            eprintln!("[ODPT] Tokyu HTML request failed: {err}");
            return Vec::new();
        }
    };

    let body = match response.text() {
        Ok(text) => text,
        Err(err) => {
            eprintln!("[ODPT] Tokyu HTML body read failed: {err}");
            return Vec::new();
        }
    };

    let document = Html::parse_document(&body);
    let item_selector = Selector::parse(".unten_info-body-item").expect("valid selector");
    let line_selector = Selector::parse(".line-name").expect("valid selector");
    let status_selector = Selector::parse(".unten_info-status-text").expect("valid selector");

    let mut rows = Vec::new();
    for item in document.select(&item_selector) {
        let line_label = item
            .select(&line_selector)
            .next()
            .map(|node| node.text().collect::<String>().trim().to_string())
            .unwrap_or_default();
        let status_text = item
            .select(&status_selector)
            .next()
            .map(|node| node.text().collect::<String>().trim().to_string())
            .filter(|text| !text.is_empty())
            .unwrap_or_else(|| "情報なし".to_string());

        rows.push(RawStatusRow {
            line_code: String::new(),
            line_label,
            status_text,
            logo_path: None,
        });
    }

    rows
}

fn fetch_odpt_traininfo(client: &Client, operator_code: &str, endpoint: &str, api_key: &str) -> Vec<RawStatusRow> {
    if api_key.is_empty() {
        eprintln!("[ODPT] missing API key for {operator_code}");
        return Vec::new();
    }

    let url = format!(
        "{endpoint}/odpt:TrainInformation?odpt:operator={operator_code}&acl:consumerKey={api_key}"
    );

    let response = match client.get(url).send() {
        Ok(response) if response.status().is_success() => response,
        Ok(response) => {
            eprintln!("[ODPT] TrainInformation status {} for {operator_code}", response.status());
            return Vec::new();
        }
        Err(err) => {
            eprintln!("[ODPT] TrainInformation request failed for {operator_code}: {err}");
            return Vec::new();
        }
    };

    let payload = match response.json::<Value>() {
        Ok(Value::Array(items)) => items,
        Ok(_) => return Vec::new(),
        Err(err) => {
            eprintln!("[ODPT] TrainInformation JSON parse failed for {operator_code}: {err}");
            return Vec::new();
        }
    };

    payload
        .iter()
        .filter_map(|item| build_row_from_odpt_item(item, operator_code))
        .collect()
}

fn build_row_from_odpt_item(item: &Value, _operator_code: &str) -> Option<RawStatusRow> {
    let railway_code = extract_odpt_code(item.get("odpt:railway"))?;
    let line_label = line_code_to_label(&railway_code)?.to_string();
    let status_text = extract_japanese_text(item.get("odpt:trainInformationText"));
    let logo_path = icon_path_from_line_code(&railway_code).map(|path| path.to_string());

    Some(RawStatusRow {
        line_code: railway_code,
        line_label,
        status_text,
        logo_path,
    })
}

fn extract_odpt_code(value: Option<&Value>) -> Option<String> {
    let value = value?;
    match value {
        Value::String(text) => Some(extract_code_from_string(text)),
        Value::Object(map) => map
            .get("@id")
            .or_else(|| map.get("uri"))
            .or_else(|| map.get("value"))
            .and_then(|inner| inner.as_str())
            .map(extract_code_from_string),
        Value::Array(items) => items.iter().find_map(|inner| extract_odpt_code(Some(inner))),
        _ => None,
    }
}

fn extract_code_from_string(value: &str) -> String {
    value.rsplit('.').next().unwrap_or(value).to_string()
}

fn extract_japanese_text(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) => text.trim().to_string(),
        Some(Value::Object(map)) => map
            .get("ja")
            .or_else(|| map.get("en"))
            .and_then(|inner| inner.as_str())
            .map(|text| text.trim().to_string())
            .filter(|text| !text.is_empty())
            .unwrap_or_else(|| "情報なし".to_string()),
        Some(Value::Array(items)) => items
            .iter()
            .find_map(|inner| inner.as_str())
            .map(|text| text.trim().to_string())
            .filter(|text| !text.is_empty())
            .unwrap_or_else(|| "情報なし".to_string()),
        _ => "情報なし".to_string(),
    }
}

fn line_code_to_label(code: &str) -> Option<&'static str> {
    match code {
        "Fukutoshin" => Some("副都心線"),
        "Namboku" => Some("南北線"),
        "Hanzomon" => Some("半蔵門線"),
        "Yurakucho" => Some("有楽町線"),
        "Chiyoda" => Some("千代田線"),
        "Tozai" => Some("東西線"),
        "Hibiya" => Some("日比谷線"),
        "Marunouchi" => Some("丸の内線"),
        "MarunouchiBranch" => Some("丸の内線方南町支線"),
        "Ginza" => Some("銀座線"),
        "Asakusa" => Some("浅草線"),
        "Mita" => Some("三田線"),
        "Shinjuku" => Some("新宿線"),
        "Oedo" => Some("大江戸線"),
        "Arakawa" => Some("都電荒川線（東京さくらトラム）"),
        "NipporiToneri" => Some("日暮里舎人ライナー"),
        "TamaMonorail" => Some("多摩モノレール"),
        "Rinkai" => Some("りんかい線"),
        "TsukubaExpress" => Some("つくばエクスプレス線"),
        "Green" => Some("横浜市営地下鉄・グリーンライン"),
        "Blue" => Some("横浜市営地下鉄・ブルーライン"),
        "Toyoko" => Some("東横線"),
        "Meguro" => Some("目黒線"),
        "TokyuShinYokohama" => Some("東急新横浜線"),
        "DenEnToshi" => Some("田園都市線"),
        "Oimachi" => Some("大井町線"),
        "Ikegami" => Some("池上線"),
        "TokyuTamagawa" => Some("東急多摩川線"),
        "Setagaya" => Some("世田谷線"),
        "Kodomonokuni" => Some("こどもの国線"),
        "Tojo" => Some("東上線"),
        "Ogose" => Some("越生線"),
        "Isesaki" => Some("伊勢崎線"),
        "TobuSkytree" => Some("スカイツリーライン"),
        "TobuSkytreeBranch" => Some("スカイツリーライン(押上-曳舟)"),
        "Kameido" => Some("亀戸線"),
        "Daishi" => Some("大師線"),
        "Sano" => Some("佐野線"),
        "Kiryu" => Some("桐生線"),
        "Koizumi" => Some("小泉線"),
        "KoizumiBranch" => Some("小泉線(支線)"),
        "Nikko" => Some("日光線"),
        "Kinugawa" => Some("鬼怒川線"),
        "TobuUrbanPark" => Some("アーバンパークライン"),
        "Yamanote" => Some("山手線"),
        "KeihinTohokuNegishi" => Some("京浜東北・根岸線"),
        "Tokaido" => Some("東海道線"),
        "ChuoRapid" => Some("中央線快速"),
        "ChuoSobuLocal" => Some("中央・総武線各駅停車"),
        "Yokosuka" => Some("横須賀線"),
        "SobuRapid" => Some("総武快速線"),
        "ShonanShinjuku" => Some("湘南新宿ライン"),
        "Utsunomiya" => Some("宇都宮線"),
        "Takasaki" => Some("高崎線"),
        "Keiyo" => Some("京葉線"),
        "Musashino" => Some("武蔵野線"),
        "Yokohama" => Some("横浜線"),
        "JobanRapid" => Some("常磐線快速"),
        "JobanLocal" => Some("常磐線各駅停車"),
        _ => None,
    }
}

fn icon_path_from_line_code(code: &str) -> Option<&'static str> {
    match code {
        "Toyoko" => Some("tokyurailway/icon_TY.png"),
        "DenEnToshi" => Some("tokyurailway/icon_DT.png"),
        "Ikegami" => Some("tokyurailway/icon_IK.png"),
        "Meguro" => Some("tokyurailway/icon_MG.png"),
        "Oimachi" => Some("tokyurailway/icon_OM.png"),
        "Setagaya" => Some("tokyurailway/icon_SG.png"),
        "TokyuTamagawa" => Some("tokyurailway/icon_TM.png"),
        "Kodomonokuni" => Some("tokyurailway/icon_KD.png"),
        "TokyuShinYokohama" => Some("tokyurailway/icon_SH.png"),
        "Chiyoda" => Some("tokyometro/icon_chiyoda.png"),
        "Fukutoshin" => Some("tokyometro/icon_fukutoshin.png"),
        "Ginza" => Some("tokyometro/icon_ginza.png"),
        "Hanzomon" => Some("tokyometro/icon_hanzomon.png"),
        "Hibiya" => Some("tokyometro/icon_hibiya.png"),
        "Marunouchi" => Some("tokyometro/icon_marunouchi.png"),
        "Namboku" => Some("tokyometro/icon_namboku.png"),
        "Tozai" => Some("tokyometro/icon_tozai.png"),
        "Yurakucho" => Some("tokyometro/icon_yurakucho.png"),
        "Oedo" => Some("toei/icon_oedo.png"),
        "Asakusa" => Some("toei/icon_asakusa.png"),
        "Mita" => Some("toei/icon_mita.png"),
        "Shinjuku" => Some("toei/icon_shinjuku.png"),
        "Arakawa" => Some("toei/icon_arakawa.png"),
        "Blue" => Some("yokohama/icon_blue.png"),
        "Green" => Some("yokohama/icon_green.png"),
        "Tojo" => Some("tobu/icon_tojo.png"),
        "Isesaki" => Some("tobu/icon_isesaki.png"),
        "TobuSkytree" => Some("tobu/icon_skytree.png"),
        "Nikko" => Some("tobu/icon_nikko.png"),
        "TobuUrbanPark" => Some("tobu/icon_urbanpark.png"),
        "Yamanote" => Some("JR/icon_JY.png"),
        "KeihinTohokuNegishi" => Some("JR/icon_JK.png"),
        "Tokaido" => Some("JR/icon_JT.png"),
        "ChuoRapid" => Some("JR/icon_JC.png"),
        "ChuoSobuLocal" => Some("JR/icon_JB.png"),
        "Yokosuka" => Some("JR/icon_JO.png"),
        "SobuRapid" => Some("JR/icon_JO.png"),
        "ShonanShinjuku" => Some("JR/icon_JS.png"),
        "Utsunomiya" => Some("JR/icon_JU.png"),
        "Takasaki" => Some("JR/icon_JU.png"),
        "Keiyo" => Some("JR/icon_JE.png"),
        "Musashino" => Some("JR/icon_JM.png"),
        "Yokohama" => Some("JR/icon_JH.png"),
        "JobanRapid" => Some("JR/icon_JJ.png"),
        "JobanLocal" => Some("JR/icon_JL.png"),
        "TamaMonorail" => Some("icon_tamamonorail.png"),
        _ => None,
    }
}

fn ensure_schema(db_path: &Path) -> Result<()> {
    if let Some(parent) = db_path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("failed to create {}", parent.display()))?;
    }

    let conn = Connection::open(db_path).with_context(|| format!("failed to open {}", db_path.display()))?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "busy_timeout", 5000_i64)?;
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS odpt_status_snapshot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            updated_at TEXT NOT NULL,
            source TEXT NOT NULL,
            total_count INTEGER NOT NULL
        );

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
        );

        CREATE INDEX IF NOT EXISTS idx_odpt_status_items_sort
        ON odpt_status_items(group_order, operator_order, item_order);
        "#,
    )?;

    Ok(())
}

fn write_snapshot(db_path: &Path, rows: &[StatusRow], updated_at: &str, source: &str) -> Result<()> {
    let mut conn = Connection::open(db_path).with_context(|| format!("failed to open {}", db_path.display()))?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "busy_timeout", 5000_i64)?;

    let tx = conn.transaction()?;
    tx.execute("DELETE FROM odpt_status_items", [])?;
    tx.execute("DELETE FROM odpt_status_snapshot WHERE id = 1", [])?;
    tx.execute(
        "INSERT INTO odpt_status_snapshot (id, updated_at, source, total_count) VALUES (1, ?1, ?2, ?3)",
        params![updated_at, source, rows.len() as i64],
    )?;

    let mut stmt = tx.prepare(
        r#"
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
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
        "#,
    )?;

    for row in rows {
        stmt.execute(params![
            row.group_order,
            row.operator_order,
            row.item_order,
            row.operator_label,
            row.line_code,
            row.line_label,
            row.status_text,
            row.display_text,
            row.logo_path.as_deref(),
        ])?;
    }

    drop(stmt);

    tx.commit()?;
    Ok(())
}
