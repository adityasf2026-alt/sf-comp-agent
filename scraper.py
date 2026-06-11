"""
SF Competitiveness Agent — Playwright scraper
Reads FSN/ASIN list from Google Sheet, crawls FK + AZ prices,
writes results to Crawl Output sheet.
"""
import asyncio
import json
import re
import os
import sys
import random
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright
from sheets_writer import SheetsWriter

IST = timezone(timedelta(hours=5, minutes=30))

SPREADSHEET_ID = "1xeVplg5lAx-GRA-2ypxLi9zxgtjoQ-HsOUd0uAQqu2Y"
FK_BASE = "https://www.flipkart.com/vega-cliff-motorbike-helmet/p/itmfcz57cwhqvvfj?pid="
AZ_BASE = "https://www.amazon.in/dp/"

# ── JS extractors ────────────────────────────────────────────────────────
FK_JS = """() => {
    const p = [...document.querySelectorAll('div,span')].filter(e => {
        try { const t = e.innerText?.trim(); return t && /^₹[\\d,]+$/.test(t) && t.length < 12; }
        catch { return false; }
    }).map(e => ({text: e.innerText.trim(), y: e.getBoundingClientRect().top}))
      .filter(e => e.y > 150 && e.y < 600).sort((a,b) => a.y - b.y);
    const price = p[0]?.text || 'NA';
    const b = document.body?.innerText || '';
    const s = b.match(/(?:Fulfilled by|Sold by)\\s+([A-Za-z][^\\n•|]{2,40}?)(?:\\s*\\n|\\s*[•|])/i);
    const fallback = price === 'NA' ? (b.match(/₹[\\d,]+/g) || [])[0] || 'NA' : price;
    return {price: fallback, seller: s?.[1]?.trim() || 'NA'};
}"""

AZ_JS = """() => {
    const pe = document.querySelector('#corePrice_feature_div .a-offscreen') ||
               document.querySelector('.a-price .a-offscreen');
    let price = pe?.innerText?.trim() || 'NA';
    let seller = document.querySelector('#sellerProfileTriggerId')?.innerText?.trim() ||
                 document.querySelector('#merchant-info a')?.innerText?.trim() || 'NA';
    if (price === 'NA') {
        const b = document.body.innerText;
        const prices = b.match(/₹[\\d,]+/g) || [];
        price = prices[1] || prices[0] || 'NA';
        seller = (b.match(/(?:Sold by|Ships from and sold by)\\s+([^\\n]+)/i) || [])[1]?.trim() || seller;
    }
    return {price, seller};
}"""


def parse_price(raw: str) -> float:
    """Strip ₹, commas, spaces → float. Returns 0 if unparseable."""
    try:
        return float(re.sub(r'[₹,\s]', '', str(raw).split()[0]))
    except Exception:
        return 0.0


def compute_flag(fsn: str, fk_price: float, az_price: float, history: list[dict]) -> str:
    """Flag logic based on trailing 10-day history."""
    if fk_price == 0 or az_price == 0:
        return "Check manually"
    if fk_price <= az_price:
        return "OK"
    # Count prior occurrences where FK > AZ in the last 10 days
    count = sum(1 for h in history if h.get("fsn") == fsn and h.get("fk_gt_az"))
    count += 1  # include current
    if count == 1:
        return "AZ Comp today"
    elif count == 2:
        return "AZ Comp 2nd time"
    else:
        return "AZ Comp 3+ time"


async def fetch_fk(page, url: str) -> dict:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(random.randint(1500, 2500))
        result = await page.evaluate(FK_JS)
        return result
    except Exception as e:
        print(f"  FK error {url}: {e}")
        return {"price": "NA", "seller": "NA"}


async def fetch_az(page, url: str) -> dict:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(random.randint(1500, 2500))
        result = await page.evaluate(AZ_JS)
        return result
    except Exception as e:
        print(f"  AZ error {url}: {e}")
        return {"price": "NA", "seller": "NA"}


async def run_crawl():
    now_ist = datetime.now(IST)
    crawl_date = now_ist.strftime("%d/%m/%Y")
    crawl_time = now_ist.strftime("%-I:%M %p IST")

    print(f"\n=== SF Competitiveness Crawl | {crawl_date} {crawl_time} ===\n")

    writer = SheetsWriter(SPREADSHEET_ID)
    products = writer.read_fsn_input()
    history  = writer.read_crawl_history()

    print(f"Products to crawl: {len(products)}")

    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        # Mask automation signals
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)

        page = await context.new_page()

        for i, prod in enumerate(products, 1):
            fsn   = prod["fsn"]
            asin  = prod["asin"]
            brand = prod["brand"]
            vert  = prod["verticals"]
            fk_url = prod["fk_url"] or (FK_BASE + fsn)
            az_url = prod["az_url"] or (AZ_BASE + asin)

            print(f"[{i:03}/{len(products)}] {brand} | {fsn[:16]}...", end=" ", flush=True)

            fk = await fetch_fk(page, fk_url)
            az = await fetch_az(page, az_url)

            fk_price = parse_price(fk["price"])
            az_price = parse_price(az["price"])
            flag = compute_flag(fsn, fk_price, az_price, history)

            print(f"FK={fk['price']} AZ={az['price']} → {flag}")

            results.append({
                "date":       crawl_date,
                "time":       crawl_time,
                "brand":      brand,
                "verticals":  vert,
                "fsn":        fsn,
                "asin":       asin,
                "fk_url":     fk_url,
                "az_url":     az_url,
                "fk_price":   fk_price or fk["price"],
                "az_price":   az_price or az["price"],
                "fk_seller":  fk["seller"],
                "az_seller":  az["seller"],
                "flag":       flag,
            })

            # Polite delay between products
            await page.wait_for_timeout(random.randint(800, 1400))

        await browser.close()

    # Write to sheet
    print(f"\nWriting {len(results)} rows to Crawl Output...")
    writer.append_crawl_output(results)
    writer.prune_old_rows()

    ok    = sum(1 for r in results if r["flag"] == "OK")
    az_c  = len(results) - ok
    print(f"\nDone. OK={ok} | AZ Comp={az_c} ({az_c/len(results):.1%})")
    return results


if __name__ == "__main__":
    asyncio.run(run_crawl())
