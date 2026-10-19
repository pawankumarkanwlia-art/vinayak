import os
import re
import json
import time
import html
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCES = [
    ("SarkariResult", "https://sarkariresult.com.cm/"),
    ("FreeJobAlert", "https://www.freejobalert.com/"),
]
SEEN_FILE = "seen_jobs.json"
MAX_NEW_PER_SOURCE = int(os.getenv("MAX_NEW_PER_SOURCE", "12"))
REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": "SarkariJobAlertBot/1.0 (personal job alerts; contact: repository owner)"
}

JOB_HINTS = re.compile(
    r"(recruit|vacanc|job|result|admit.?card|answer.?key|notification|"
    r"application.?form|online.?form|sarkari|government|bharti|"
    r"rojgar|exam|apprentice|officer|constable|teacher|clerk|"
    r"railway|ssc|upsc|bank|police|court|army|navy|air.?force)",
    re.I,
)
NON_JOB_HINTS = re.compile(
    r"(privacy|disclaimer|contact.?us|about.?us|advertis|cookie|login|"
    r"register|facebook|instagram|youtube|telegram|whatsapp|category/|tag/)",
    re.I,
)
QUALIFICATION_HINTS = re.compile(
    r"(qualification|educational qualification|eligibility|10th|12th|"
    r"graduate|graduation|post.?graduate|diploma|degree|ITI|B\.?Tech|"
    r"B\.?Ed|M\.?Sc|qualification details)",
    re.I,
)
LAST_DATE_HINTS = re.compile(
    r"(last date|closing date|apply before|online application last date|"
    r"last date to apply|application deadline|महत्वपूर्ण तिथि|अंतिम तिथि)",
    re.I,
)

def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s

def clean_url(url):
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    # Drop common tracking parameters while preserving useful query strings only when present.
    if parsed.netloc.lower().startswith("www."):
        netloc = parsed.netloc.lower()
    else:
        netloc = parsed.netloc.lower()
    return parsed._replace(netloc=netloc, fragment="").geturl().rstrip("/")

def same_domain(url, base_url):
    a = urlparse(url).netloc.lower().removeprefix("www.")
    b = urlparse(base_url).netloc.lower().removeprefix("www.")
    return a == b

def fetch(session, url):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "").lower()
        if "text/html" not in ctype and "xml" not in ctype and not url.endswith(".xml"):
            return None
        return r.text
    except requests.RequestException as exc:
        logging.warning("Fetch failed for %s: %s", url, exc)
        return None

def parse_sitemap(session, base_url):
    candidates = []
    sitemap_urls = [urljoin(base_url, "sitemap.xml"), urljoin(base_url, "sitemap_index.xml")]
    for sm_url in sitemap_urls:
        raw = fetch(session, sm_url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
            locs = [el.text.strip() for el in root.iter() if el.tag.lower().endswith("loc") and el.text]
        except ET.ParseError:
            continue
        # Sitemap index: inspect a limited number of child sitemaps.
        child_maps = [u for u in locs if u.lower().endswith(".xml")]
        page_urls = [u for u in locs if not u.lower().endswith(".xml")]
        for child in child_maps[:8]:
            child_raw = fetch(session, child)
            if not child_raw:
                continue
            try:
                child_root = ET.fromstring(child_raw)
                page_urls.extend(el.text.strip() for el in child_root.iter()
                                 if el.tag.lower().endswith("loc") and el.text)
            except ET.ParseError:
                pass
            time.sleep(0.4)
        candidates.extend(page_urls)
        if candidates:
            break
    return candidates

def discover_links(session, source_name, base_url):
    urls = []
    homepage = fetch(session, base_url)
    if homepage:
        soup = BeautifulSoup(homepage, "html.parser")
        for a in soup.find_all("a", href=True):
            href = clean_url(urljoin(base_url, a["href"].strip()))
            if not href or not same_domain(href, base_url):
                continue
            text = a.get_text(" ", strip=True)
            combined = f"{text} {href}"
            if NON_JOB_HINTS.search(combined):
                continue
            if JOB_HINTS.search(combined):
                urls.append(href)

    # Sitemaps can reveal newly published pages not prominent on the home page.
    for url in parse_sitemap(session, base_url):
        normalized = clean_url(url)
        if normalized and same_domain(normalized, base_url) and not NON_JOB_HINTS.search(normalized):
            if JOB_HINTS.search(normalized):
                urls.append(normalized)

    # Keep stable order and unique links.
    seen = set()
    out = []
    for u in urls:
        if u not in seen and u.rstrip("/") != base_url.rstrip("/"):
            seen.add(u)
            out.append(u)
    logging.info("%s: discovered %d candidate URLs", source_name, len(out))
    return out

def extract_detail(session, source_name, url):
    raw = fetch(session, url)
    if not raw:
        return None
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        node.decompose()

    title = ""
    for selector in ("h1", "article h2", "main h2", "title"):
        node = soup.select_one(selector)
        if node:
            title = node.get_text(" ", strip=True)
            if title:
                break
    title = re.sub(r"\s+", " ", html.unescape(title)).strip()
    if not title:
        return None

    body = soup.get_text("\n", strip=True)
    body = re.sub(r"[ \t]+", " ", body)
    lines = [re.sub(r"\s+", " ", x).strip() for x in body.splitlines()]
    lines = [x for x in lines if x]
    # Avoid sending pages that are probably category pages or unrelated.
    if not JOB_HINTS.search(title + " " + url):
        return None

    qualification = "उपलब्ध नहीं — कृपया आधिकारिक नोटिफिकेशन देखें"
    last_date = "उपलब्ध नहीं — कृपया आधिकारिक नोटिफिकेशन देखें"

    for i, line in enumerate(lines):
        if QUALIFICATION_HINTS.search(line):
            qualification = line[:450]
            if len(qualification) < 100 and i + 1 < len(lines):
                qualification += " " + lines[i + 1][:250]
            break

    for i, line in enumerate(lines):
        if LAST_DATE_HINTS.search(line):
            last_date = line[:450]
            if len(last_date) < 100 and i + 1 < len(lines):
                last_date += " " + lines[i + 1][:250]
            break

    # If the page has no explicit application deadline, do not guess.
    return {
        "source": source_name,
        "title": title[:240],
        "url": url,
        "qualification": qualification,
        "last_date": last_date,
        "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2, sort_keys=True)

def send_telegram(session, token, chat_id, job):
    text = (
        "🆕 <b>नई सरकारी नौकरी / भर्ती अपडेट</b>\n\n"
        f"<b>पोस्ट:</b> {html.escape(job['title'])}\n"
        f"<b>स्रोत:</b> {html.escape(job['source'])}\n"
        f"<b>योग्यता:</b> {html.escape(job['qualification'])}\n"
        f"<b>अंतिम तिथि:</b> {html.escape(job['last_date'])}\n\n"
        f"🔗 <a href=\"{html.escape(job['url'], quote=True)}\">पूरी जानकारी / आधिकारिक पेज</a>\n"
        f"<i>जाने से पहले आधिकारिक नोटिफिकेशन में विवरण सत्यापित करें।</i>"
    )
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = session.post(api_url, json={
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=REQUEST_TIMEOUT)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200 or not payload.get("ok"):
        raise RuntimeError(f"Telegram send failed: HTTP {response.status_code}; {payload.get('description', response.text[:300])}")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment secret.")

    session = get_session()
    seen = load_seen()
    newly_found = []

    for source_name, base_url in SOURCES:
        urls = discover_links(session, source_name, base_url)
        # New URLs only; details are fetched only for not-yet-seen candidates.
        fresh_urls = [u for u in urls if u not in seen][:MAX_NEW_PER_SOURCE]
        for url in fresh_urls:
            job = extract_detail(session, source_name, url)
            # Mark every checked candidate as seen to avoid repeated bad pages.
            seen[url] = {
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "title": job["title"] if job else "",
            }
            if job:
                newly_found.append(job)
            time.sleep(0.8)

    # Save state even if no valid new jobs were found. Workflow commits this file.
    save_seen(seen)

    sent = 0
    for job in newly_found:
        try:
            send_telegram(session, token, chat_id, job)
            sent += 1
            logging.info("Sent: %s", job["title"])
            time.sleep(1.2)
        except Exception as exc:
            # If a send fails, remove it from seen so the next run can retry.
            seen.pop(job["url"], None)
            logging.error("Could not send %s: %s", job["url"], exc)
    save_seen(seen)
    logging.info("Finished. New valid jobs: %d; Telegram messages sent: %d", len(newly_found), sent)

if __name__ == "__main__":
    main()
