# main.py
# FastAPI + Playwright flight search for budgetticket.in
# Run: uvicorn main:app --reload
# First time only: pip install fastapi uvicorn playwright && python -m playwright install

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from typing import List, Dict
from datetime import datetime
import re, json

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

HOME = "https://www.budgetticket.in"
RESULTS_TIMEOUT = 60_000  # ms

TIME_RE   = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")
FLTNO_RE  = re.compile(r"\b([A-Z]{1,2}[A-Z]?[- ]?\d{2,4})\b")
PRICE_RE  = re.compile(r"₹\s*[\d,]+")

app = FastAPI(title="Flight Search API")

# ---------- tiny helpers ----------
def _safe_text(loc, timeout=1500):
    try:
        t = loc.first.inner_text(timeout=timeout).strip()
        return t if t else None
    except Exception:
        return None

def _parse_date(d: str):
    """
    Accepts YYYY-MM-DD or YYYY/MM/DD or DD-MM-YYYY (best effort).
    Returns (day, month, year) as ints.
    """
    try:
        # try ISO first
        dt = datetime.fromisoformat(d.replace("/", "-"))
        return dt.day, dt.month, dt.year
    except Exception:
        pass
    # fallback common formats
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(d, fmt)
            return dt.day, dt.month, dt.year
        except Exception:
            continue
    raise ValueError("Unsupported date format. Use YYYY-MM-DD.")

# ---------- page actions ----------
def fill_city_autocomplete(input_locator, city_name: str):
    input_locator.click()
    input_locator.fill("")
    input_locator.type(city_name, delay=50)
    input_locator.page.wait_for_timeout(800)
    input_locator.press("Enter")

def pick_specific_departure(page, day: int, month: int, year: int):
    # open the Departure calendar (first date label)
    page.locator("label.datepicker.search-date").first.click()

    # scope to the visible departure popup
    cal = page.locator(
        "div.calender-box >> div.modalDatePicker"
    ).filter(has=page.get_by_text("Select Departure Date")).first
    cal.wait_for(state="visible", timeout=10_000)

    d, m, y = str(day), str(month), str(year)

    # works for both emp_Cells (no price) and cnt_Cells (with price)
    day_cell = cal.locator(
        "td[ng-click^='SetDate(']"
        f"[ng-click*='\"{d}\"']"
        f"[ng-click*='\"{m}\"']"
        f"[ng-click*='\"{y}\"']"
    ).first

    day_cell.wait_for(state="visible", timeout=10_000)
    day_cell.click()

def wait_for_results(page):
    page.wait_for_load_state("networkidle", timeout=RESULTS_TIMEOUT)
    for sel in [
        "div.search-card",
        "button:has-text('Book')",
        "text=/Non- Stop|Stops|Price/i",
    ]:
        try:
            page.wait_for_selector(sel, state="visible", timeout=7000)
            return
        except PlaywrightTimeoutError:
            continue
    # small grace period
    page.wait_for_timeout(1500)

def extract_flight_results(page, origin: str, destination: str) -> List[Dict]:
    results = []
    cards = page.locator("div.search-card")
    count = cards.count()

    for i in range(count):
        card = cards.nth(i)

        # Airline (first bold h6)
        airline = _safe_text(card.locator("p.h6.responsive-bold"))

        # Flight number (explicit ng-binding node, shown in your DOM)
        # p.ng-binding that looks like "6E-2561"
        fltno_node = card.locator("p.ng-binding").filter(
            has_text=re.compile(r"[A-Za-z]{1,2}[A-Za-z]?[- ]?\d{2,4}")
        ).first
        flight_number = _safe_text(fltno_node)
        if not flight_number:
            # regex fallback over the whole card
            card_txt = card.inner_text().strip()
            m = FLTNO_RE.search(card_txt)
            flight_number = m.group(0) if m else ""

        # Times – safest is to regex two hh:mm
        card_txt = card.inner_text().strip()
        times = TIME_RE.findall(card_txt)
        departure = times[0] if len(times) > 0 else ""
        arrival   = times[1] if len(times) > 1 else ""

        # Price
        raw_price = _safe_text(card.locator(":text-matches('\\₹')"))
        if not raw_price:
            raw_price = _safe_text(card.locator("span, p, div").filter(has_text=re.compile("₹")))
        price_match = PRICE_RE.search(raw_price or "")
        price = price_match.group(0) if price_match else (raw_price or "")

        results.append({
            "airline": airline or "",
            "flight_number": flight_number or "",
            "departure": departure,
            "arrival": arrival,
            "price": price,
            "origin": origin,
            "destination": destination,
            "searchdatetime": datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        })

    return results

# ---------- core scraper ----------
def scrape(origin: str, destination: str, day: int, month: int, year: int) -> List[Dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()

        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=45_000)

            # dismiss any consent/popups if present
            for sel in ["button:has-text('Accept')", "text=I Agree", "button:has-text('OK')"]:
                try:
                    page.locator(sel).first.click(timeout=1500)
                except PlaywrightTimeoutError:
                    pass

            origin_input = page.locator("form.flight-search-bg input[placeholder='Select Origin City']").nth(0)
            dest_input   = page.locator("form.flight-search-bg input[placeholder='Select Destination City']").nth(0)

            fill_city_autocomplete(origin_input, origin)
            fill_city_autocomplete(dest_input,   destination)

            pick_specific_departure(page, day, month, year)

            page.locator("input[type='submit'][value*='Search'], button:has-text('Search')").first.click()
            wait_for_results(page)

            data = extract_flight_results(page, origin, destination)
            return data

        finally:
            context.close()
            browser.close()

# ---------- API ----------
@app.get("/flight-search")
def flight_search(
    origin: str = Query(..., description="Origin city name, e.g. Bangalore"),
    destination: str = Query(..., description="Destination city name, e.g. Delhi"),
    journey_date: str = Query(..., description="Date in YYYY-MM-DD")
):
    try:
        d, m, y = _parse_date(journey_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        results = scrape(origin, destination, d, m, y)
    except Exception as e:
        # Surface a concise message
        raise HTTPException(status_code=500, detail=f"Scrape failed: {e}")

    return JSONResponse(content=results)
