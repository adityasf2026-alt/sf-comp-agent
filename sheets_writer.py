"""
Google Sheets reader/writer for SF Competitiveness Agent.
Uses gspread with service account credentials from GOOGLE_CREDENTIALS env var.
"""
import json
import os
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
IST = timezone(timedelta(hours=5, minutes=30))
CRAWL_SHEET = "Crawl Output"
INPUT_SHEET = "FSN Input"
KEEP_DAYS = 10


def _get_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        raise EnvironmentError("GOOGLE_CREDENTIALS env var not set")
    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return gspread.authorize(creds)


class SheetsWriter:
    def __init__(self, spreadsheet_id: str):
        self.sid = spreadsheet_id
        client = _get_client()
        self.spreadsheet = client.open_by_key(spreadsheet_id)

    # ── Read FSN Input ──────────────────────────────────────────────────
    def read_fsn_input(self) -> list[dict]:
        try:
            ws = self.spreadsheet.worksheet(INPUT_SHEET)
        except Exception:
            ws = self.spreadsheet.get_worksheet(0)
        print(f"  Reading from sheet: '{ws.title}'")
        rows = ws.get_all_values()
        # Skip header rows — find rows where col 5 (FSN) looks like a real FSN
        products = []
        for r in rows:
            if len(r) < 6:
                continue
            fsn = r[4].strip()
            asin = r[5].strip() if len(r) > 5 else ""
            # Skip headers / placeholder rows
            if not fsn or fsn in ("FSN", "To be filled by User") or len(fsn) < 10:
                continue
            products.append({
                "brand":     r[2].strip() if len(r) > 2 else "",
                "verticals": r[3].strip() if len(r) > 3 else "",
                "fsn":       fsn,
                "asin":      asin,
                "fk_url":    r[6].strip() if len(r) > 6 else "",
                "az_url":    r[7].strip() if len(r) > 7 else "",
            })
        return products

    # ── Read Crawl Output history (last 10 days) ────────────────────────
    def read_crawl_history(self) -> list[dict]:
        try:
            ws = self.spreadsheet.worksheet(CRAWL_SHEET)
            rows = ws.get_all_values()
        except Exception:
            return []
        now = datetime.now(IST)
        cutoff = now - timedelta(days=KEEP_DAYS)
        history = []
        for r in rows[1:]:  # skip header
            if len(r) < 13:
                continue
            try:
                row_date = datetime.strptime(r[0], "%d/%m/%Y").replace(tzinfo=IST)
                if row_date < cutoff:
                    continue
            except Exception:
                continue
            try:
                fk_p = float(str(r[8]).replace(",", "").replace("₹", "").strip())
                az_p = float(str(r[9]).replace(",", "").replace("₹", "").strip())
            except Exception:
                continue
            history.append({
                "fsn":      r[4],
                "date":     r[0],
                "fk_gt_az": fk_p > az_p,
            })
        return history

    # ── Append crawl rows ───────────────────────────────────────────────
    def append_crawl_output(self, results: list[dict]):
        ws = self.spreadsheet.worksheet(CRAWL_SHEET)
        # Add header if sheet is empty
        existing = ws.get_all_values()
        if not existing:
            ws.append_row([
                "Date", "Crawl Time", "Brand", "Verticals", "FSN", "AZ ASIN",
                "FK URL", "AZ URL", "FK Price", "AZ Price",
                "FK Seller Name", "AZ Seller Name", "Flag"
            ])
        rows = []
        for r in results:
            rows.append([
                r["date"], r["time"], r["brand"], r["verticals"],
                r["fsn"], r["asin"], r["fk_url"], r["az_url"],
                r["fk_price"], r["az_price"],
                r["fk_seller"], r["az_seller"], r["flag"],
            ])
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        print(f"  Appended {len(rows)} rows to '{CRAWL_SHEET}'")

    # ── Prune rows older than 10 days ───────────────────────────────────
    def prune_old_rows(self):
        ws = self.spreadsheet.worksheet(CRAWL_SHEET)
        rows = ws.get_all_values()
        if not rows:
            return
        now = datetime.now(IST)
        cutoff = now - timedelta(days=KEEP_DAYS)
        header = rows[0]
        kept = [header]
        pruned = 0
        for r in rows[1:]:
            try:
                row_date = datetime.strptime(r[0], "%d/%m/%Y").replace(tzinfo=IST)
                if row_date < cutoff:
                    pruned += 1
                    continue
            except Exception:
                pass
            kept.append(r)
        if pruned > 0:
            ws.clear()
            ws.update(kept, value_input_option="USER_ENTERED")
            print(f"  Pruned {pruned} rows older than {KEEP_DAYS} days")
