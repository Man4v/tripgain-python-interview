# flight_search.py
from datetime import date, timedelta, datetime
import json, re
from playwright.sync_api import Playwright, sync_playwright, TimeoutError as PlaywrightTimeoutError

HOME = "https://www.budgetticket.in"

ORIGIN_CITY = "Bangalore"
DEST_CITY   = "Delhi"
RESULTS_TIMEOUT = 60_000  # ms
TIME_RE   = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")
FLTNO_RE  = re.compile(r"\b([A-Z]{1,2}[A-Z]?[- ]?\d{2,4})\b")
PRICE_RE  = re.compile(r"₹\s*[\d,]+")

# ---------- DATE PICKER (kept from your working version) ----------
def pick_specific_departure(page, day: int, month: int, year: int):
    # Click the Departure label to open the calendar
    page.locator("label.datepicker.search-date").first.click()

    # Scope to the visible departure popup
    cal = page.locator(
        "div.calender-box >> div.modalDatePicker"
    ).filter(has=page.get_by_text("Select Departure Date")).first
    cal.wait_for(state="visible", timeout=10_000)

    d, m, y = str(day), str(month), str(year)

    # Works for emp_Cells (no price yet) and cnt_Cells (with price row)
    day_cell = cal.locator(
        "td[ng-click^='SetDate(']"
        f"[ng-click*='\"{d}\"']"
        f"[ng-click*='\"{m}\"']"
        f"[ng-click*='\"{y}\"']"
    ).first

    day_cell.wait_for(state="visible", timeout=10_000)
    day_cell.click()

# ---------- AUTOCOMPLETE ----------
def fill_city_autocomplete(input_locator, city_name: str):
    input_locator.click()
    input_locator.fill("")
    input_locator.type(city_name, delay=50)
    input_locator.page.wait_for_timeout(800)
    input_locator.press("Enter")

# ---------- RESULTS WAIT ----------
def wait_for_results(page):
    page.wait_for_load_state("networkidle", timeout=RESULTS_TIMEOUT)
    # any of these appearing means cards are rendered
    for sel in [
        "div.search-card",                 # main card container seen in DOM
        "button:has-text('Book')",         # each card has a Book button
        "text=/Non- Stop|Stops|Price/i",
    ]:
        try:
            page.wait_for_selector(sel, state="visible", timeout=7000)
            return
        except PlaywrightTimeoutError:
            continue
    page.wait_for_timeout(1500)

# ---------- SMALL HELPERS ----------
def _safe_text(loc, timeout=1500):
    try:
        t = loc.first.inner_text(timeout=timeout).strip()
        return t if t else None
    except Exception:
        return None

def _regex_first(text, pattern):
    m = re.search(pattern, text, flags=re.I)
    return m.group(0).strip() if m else None

# ---------- EXTRACTION ----------
def extract_flight_results(page):
    results = []

    cards = page.locator("div.search-card")
    count = cards.count()

    for i in range(count):
        card = cards.nth(i)

        # Airline
        airline = _safe_text(card.locator("p.h6.responsive-bold"))

        # Flight number – visible <p> with that class; fallback to regex
        flight_number = _safe_text(
            card.locator("p.mb-0.d-inline.d-lg-block.ng-binding:visible")
                .filter(has_text=re.compile(r"[A-Za-z]{1,2}[A-Za-z]?[- ]?\d{2,4}"))
        )
        if not flight_number:
            card_txt = card.inner_text().strip()
            m = FLTNO_RE.search(card_txt)
            flight_number = m.group(1) if m else ""

        # Times – take first two hh:mm in the card text as depart/arrive
        card_txt = card.inner_text().strip()
        times = TIME_RE.findall(card_txt)
        departure = times[0] if len(times) > 0 else ""
        arrival   = times[1] if len(times) > 1 else ""

        # Price – first visible with ₹, then clean
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
            "origin": ORIGIN_CITY,
            "destination": DEST_CITY,
            "searchdatetime": datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        })

    return results

def save_results_to_json(results, filename="flight_results.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"📝 Saved {len(results)} flights to {filename}")

# ---------- MAIN ----------
def run(playwright: Playwright):
    browser = playwright.chromium.launch(headless=False, args=["--start-maximized"])
    context = browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()

    page.goto(HOME, wait_until="domcontentloaded")
    for sel in ["button:has-text('Accept')", "text=I Agree", "button:has-text('OK')"]:
        try:
            page.locator(sel).first.click(timeout=1500)
        except PlaywrightTimeoutError:
            pass

    origin_input = page.locator("form.flight-search-bg input[placeholder='Select Origin City']").nth(0)
    dest_input   = page.locator("form.flight-search-bg input[placeholder='Select Destination City']").nth(0)

    fill_city_autocomplete(origin_input, ORIGIN_CITY)
    fill_city_autocomplete(dest_input,   DEST_CITY)

    # your working date picker call
    pick_specific_departure(page, 15, 11, 2025)

    page.locator("input[type='submit'][value*='Search'], button:has-text('Search')").first.click()
    wait_for_results(page)

    print("✅ Results page loaded, extracting…")
    results = extract_flight_results(page)
    save_results_to_json(results, "flight_results.json")
    print(f"Total Flights Extracted: {len(results)}")

if __name__ == "__main__":
    with sync_playwright() as p:
        run(p)
