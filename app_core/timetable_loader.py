from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .config import CSV_CACHE_MAXSIZE, EXCEL_CACHE_MAXSIZE

logger = logging.getLogger(__name__)


def _normalize_text(value: object) -> str:
    text = str(value).strip()
    if text.lower() in {"nan", "na", "<na>", "-", "ー"}:
        return ""
    return text


def _read_csv_dataframe(csv_path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(csv_path, encoding="utf-8", header=0, keep_default_na=False, dtype=str)
    except UnicodeDecodeError:
        try:
            return pd.read_csv(csv_path, encoding="cp932", header=0, keep_default_na=False, dtype=str)
        except Exception as exc:
            logger.error("CSV read error (cp932): %s - %s", csv_path, exc)
            return None
    except Exception as exc:
        logger.error("CSV read error (utf-8): %s - %s", csv_path, exc)
        return None


@lru_cache(maxsize=CSV_CACHE_MAXSIZE)
def load_csv_schedule_cached(path: str, mtime_ns: int) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []

    df = _read_csv_dataframe(csv_path)
    if df is None or df.empty:
        return []

    out: list[dict[str, str]] = []
    num_columns = len(df.columns)
    if num_columns == 0:
        logger.warning("CSV has no columns: %s", csv_path)
        return []

    for _, row in df.iterrows():
        try:
            time_str = str(row.iloc[0]).strip()
            if not time_str:
                continue

            parts = time_str.split(":")
            if len(parts) != 2:
                continue

            h, m = int(parts[0]), int(parts[1])
            formatted_time = f"{h:02d}:{m:02d}"
            pd.Timestamp(year=2000, month=1, day=1, hour=h, minute=m)

            train_type = ""
            if num_columns > 1:
                train_type = _normalize_text(row.iloc[1])

            destination = ""
            if num_columns > 2:
                destination = _normalize_text(row.iloc[2])

            out.append({"time": formatted_time, "type": train_type, "dest": destination})
        except (ValueError, TypeError, IndexError):
            continue

    if not out:
        logger.info(
            "No valid schedule entries extracted from %s. Please check CSV format and content.",
            csv_path,
        )

    return sorted(out, key=lambda item: item["time"])


def _read_excel_dataframe(excel_path: Path, sheet: str) -> pd.DataFrame | None:
    try:
        logger.debug("Excel file: %s", excel_path)
        logger.debug("Sheet list: %s", pd.ExcelFile(excel_path).sheet_names)
        return pd.read_excel(excel_path, sheet_name=sheet)
    except Exception as exc:
        logger.error("Excel read error: %s - %s", excel_path, exc)
        return None


@lru_cache(maxsize=EXCEL_CACHE_MAXSIZE)
def load_excel_schedule_cached(path: str, mtime_ns: int, sheet: str, column: str) -> list[str]:
    excel_path = Path(path)
    if not excel_path.exists():
        return []

    df = _read_excel_dataframe(excel_path, sheet)
    if df is None or df.empty:
        return []

    logger.debug("Loaded columns: %s", df.columns.tolist())
    if "時" not in df.columns:
        df.rename(columns={df.columns[0]: "時"}, inplace=True)

    if column not in df.columns:
        if len(df.columns) > 1:
            fallback_column = str(df.columns[1])
            logger.warning("指定列 '%s' が見つかりません。第2列 '%s' を使用します。", column, fallback_column)
            column = fallback_column
        else:
            logger.warning("指定列 '%s' が見つかりません。", column)
            return []
    else:
        logger.debug("Using column: %s", column)

    out: list[str] = []
    for _, row in df.iterrows():
        h = str(row["時"]).strip()
        if not h.isdigit() or pd.isna(row[column]):
            continue
        for minute in str(row[column]).split():
            if minute.isdigit():
                out.append(f"{h.zfill(2)}:{minute.zfill(2)}")
    return out