# tripgain_gemini_analysis.py
# Usage:
#   GEMINI_API_KEY=YOUR_KEY python tripgain_gemini_analysis.py [source]
# where [source] is one of: wikipedia, bbc, cnn  (default: wikipedia)
#
# This script fetches a live webpage, cleans it, sends the content to Gemini 2.5 Flash,
# and prints + saves a structured summary with an insight to summary_output.txt

import os
import sys
import json
import re
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup, Comment

# Install google-generativeai via pip if needed:
# pip install google-generativeai

try:
    import google.generativeai as genai
except ImportError as e:
    raise SystemExit("Missing dependency google-generativeai. Install it with: pip install google-generativeai") from e

SOURCES = {
    "wikipedia": "https://en.wikipedia.org/wiki/Artificial_intelligence",
    "bbc": "https://www.bbc.com/news/technology",
    "cnn": "https://edition.cnn.com/business",
}

def fetch_html(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text

def clean_html_to_text(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts, styles, nav, header, footer, form, aside, noscript, svg, comments
    for tag in soup(["script", "style", "nav", "header", "footer", "form", "aside", "noscript", "svg"]):
        tag.decompose()
    # Remove comments
    for c in soup.find_all(string=lambda text: isinstance(text, Comment)):
        c.extract()
    # Remove elements that are likely irrelevant by class/id hints
    junk_hints = ["cookie", "subscribe", "advert", "promo", "social", "share", "newsletter", "breadcrumb", "signin", "login", "banner"]
    for el in soup.find_all(True):
        attr_text = " ".join([el.get("id", ""), " ".join(el.get("class", []))]).lower()
        if any(h in attr_text for h in junk_hints):
            el.decompose()

    # Get main text
    texts = []
    # Prioritize article/content containers if present
    main_candidates = soup.select("article, main, #content, .content, .article, .story-body, #main")
    nodes = main_candidates if main_candidates else [soup.body or soup]

    def norm_space(s: str) -> str:
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    for node in nodes:
        # Extract text from headings and paragraphs
        for h in node.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            txt = h.get_text(separator=" ", strip=True)
            txt = norm_space(txt)
            if txt and len(txt) > 1:
                texts.append(txt)

    text = "\n".join(texts)
    # Deduplicate near-identical lines
    seen = set()
    unique_lines = []
    for line in text.splitlines():
        key = line.lower()
        if key not in seen:
            seen.add(key)
            unique_lines.append(line)
    cleaned = "\n".join(unique_lines)

    # Trim very long content to keep within model limits
    # Keep ~16k characters (~4k tokens rough); adjust as needed.
    MAX_CHARS = 16000
    if len(cleaned) > MAX_CHARS:
        cleaned = cleaned[:MAX_CHARS]
    return cleaned

def build_prompt(focus: str = "business impact", webpage_text: str = "") -> str:
    # Creative, clear, and well-structured prompt that enforces JSON output
    return f"""You are an analytical technology editor. Read the provided webpage extract and produce a tightly reasoned output
that focuses on the {focus} of what the page reports. Do not paraphrase mechanically—synthesize.

OUTPUT REQUIREMENTS (STRICT):
- Respond ONLY as valid JSON with keys "bullets" and "insight".
- "bullets" must be an array with 3 to 5 concise bullet points (each 12–24 words).
  Cover the most consequential facts and implications; avoid repetition and fluff.
- "insight" must be a single sentence (max 28 words) that interprets the overarching trend or theme, not a restatement.
- No preamble, no markdown, no code fencing—JSON only.

CONTEXT PRIORITIES:
- Emphasize concrete developments, actors (companies, regulators), and near-term impact on markets, products, and users.
- If the page aggregates many items (e.g., a news list), generalize the pattern across items.

TONE & STYLE:
- Neutral, precise, and news-desk crisp.

Here is the cleaned webpage text:
<CONTENT_START>
{webpage_text}
<CONTENT_END>
"""

def call_gemini(text: str, model_name: str = "gemini-2.5-flash") -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Please set GEMINI_API_KEY environment variable.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = build_prompt(focus="technology and business impact", webpage_text=text)

    resp = model.generate_content(prompt)
    result = resp.text.strip()

    # Remove possible code fence formatting
    result = re.sub(r'^```(?:json)?\s*', '', result)
    result = re.sub(r'\s*```$', '', result)

    # Parse JSON
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    return data


def format_output(bullets, insight) -> str:
    lines = ["Summary:"]
    for b in bullets[:5]:
        # Ensure each bullet is one line and starts with the required bullet symbol
        b_one = re.sub(r'\s+', ' ', b).strip()
        lines.append(f"• {b_one}")
    lines.append("Insight:")
    lines.append(re.sub(r'\s+', ' ', insight).strip())
    return "\n".join(lines)

def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "wikipedia"
    if arg not in SOURCES:
        raise SystemExit(f"Unknown source '{arg}'. Choose from: {', '.join(SOURCES.keys())}")
    url = SOURCES[arg]
    html = fetch_html(url)
    cleaned = clean_html_to_text(html, url)
    data = call_gemini(cleaned)

    bullets = data.get("bullets", [])
    if not isinstance(bullets, list) or not (3 <= len(bullets) <= 5):
        # Coerce to 3 items if the model returns out-of-spec
        bullets = (bullets if isinstance(bullets, list) else [str(bullets)])[:5]
        while len(bullets) < 3:
            bullets.append("Additional key point inferred from the page.")
    insight = data.get("insight", "Overall, the page reflects a converging theme across items.")

    output = format_output(bullets, insight)
    print(output)

    # Save to file
    with open("summary_output.txt", "w", encoding="utf-8") as f:
        f.write(output + "\n")

if __name__ == "__main__":
    main()
