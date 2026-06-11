"""
Google Sheets reader/writer for SF Competitiveness Agent.
Uses service account credentials from GOOGLE_CREDENTIALS env var (JSON string).
"""
import json
import os
from datetime import datetime, timezone, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
IST = timezone(timedelta(hours=5, minutes=30))
CRAWL_SHEET = "Crawl Output"
INPUT_SHEET = "FSN Input"
KEEP_DAYS = 10


def _get_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        raise EnvironmentError("GOOGLE_CREDENTIALS env var not set")
    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


class SheetsWriter:
    def __init__(self, spreadsheet_id: str):
        self.sid = spreadsheet_id
        self.svc = _get_service()

    def _get(self, range_: str) -> list:
        res = self.svc.spreadsheets().values().get(
            spreadsheetId=self.sid, range=range_
        ).execute()
        return res.get("values", [])

    def _append(self, range_: str, values: list):
        self.svc.spreadsheets().values().append(
            spreadsheetId=self.sid,
            range=range_,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

    def _clear_and_set(self, range_: str, values: list):
        self.svc.spreadsheets().values().clear(
            spreadsheetId=self.sid, range=range_
        ).execute()
        if values:
            self.svc.spreadsheets().values().update(
                spreadsheetId=self.sid,
                range=range_,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()

    # ── Read FSN Input ──────────────────────────────────────────────────
    def read_fsn_input(self) -> list[dict]:
        rows = self._get(f"{INPUT_SHEET}!A1:H200")
        if not rows:
            return []
        # Find the data header row (row with "FSN" in it)
        data_rows = [r for r in rows if len(r) >= 5 and r[4] and r[4] not in ("FSN", "To be filled by User", "")]
        products = []
        for r in data_rows:
            products.append({
                "brand":     r[2] if len(r) > 2 else "",
                "verticals": r[3] if len(r) > 3 else "",
                "fsn":       r[4] if len(r) > 4 else "",
                "asin":      r[5] if len(r) > 5 else "",
                "fk_url":    r[6] if len(r) > 6 else "",
                "az_url":    r[7] if len(r) > 7 else "",
            })
        return [p for p in products if p["fsn"] and p["asin"]]

    # ── Read Crawl Output history (last 10 days) ────────────────────────
    def read_crawl_history(self) -> list[dict]:
        rows = self._get(f"{CRAWL_SHEET}!A2:M5000")
        now = datetime.now(IST)
        cutoff = now - timedelta(days=KEEP_DAYS)
        history = []
        for r in rows:
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
        # Write header if sheet is empty
        existing = self._get(f"{CRAWL_SHEET}!A1:A1")
        if not existing:
            header = [["Date","Crawl Time","Brand","Verticals","FSN","AZ ASIN",
                       "FK URL","AZ URL","FK Price","AZ Price","FK Seller Name","AZ Seller Name","Flag"]]
            self._append(f"{CRAWL_SHEET}!A1", header)

        rows = []
        for r in results:
            rows.append([
                r["date"], r["time"], r["brand"], r["verticals"],
                r["fsn"], r["asin"], r["fk_url"], r["az_url"],
                r["fk_price"], r["az_price"],
                r["fk_seller"], r["az_seller"], r["flag"],
            ])
        self._append(f"{CRAWL_SHEET}!A2", rows)
        print(f"  Appended {len(rows)} rows to '{CRAWL_SHEET}'")

    # ── Prune rows older than 10 days ───────────────────────────────────
    def prune_old_rows(self):
        rows = self._get(f"{CRAWL_SHEET}!A1:M5000")
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
            self._clear_and_set(f"{CRAWL_SHEET}!A1", kept)
            print(f"  Pruned {pruned} rows older than {KEEP_DAYS} days")
