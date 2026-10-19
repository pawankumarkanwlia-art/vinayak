import os
import re
import json
import html
import logging
from urllib.parse import urljoin, urlparse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCES = [
    ("SarkariResult", "https://sarkariresult.com.cm/"),
    ("FreeJobAlert", "https://www.freejobalert.com/"),
]
SEEN_FILE = Path("seen_jobs.json")
MAX_LINKS_PER_SOURCE = 35
TIMEOUT = 25

SOCIAL_LINKS = """
📲 <b>हमारे साथ जुड़ें</b>
🟢 <a href="https://chat.whatsapp.com/JrmKMtnVp8YJuc31I0C9u0">WhatsApp Group</a>
🟢 <a href="https://whatsapp.com/channel/0029Vb6K1dpBlHphKeFhws0Z">WhatsApp Channel</a>
🔵 <a href="https://t.me/divyacybercafe">Telegram Channel</a>
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def get_page(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            return None
        response.encoding = response.apparent_encoding or response.encoding
        return response.text
    except requests.RequestException as exc:
        logging.warning("Page fetch failed (%s): %s", url, exc)
        return None


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip(" \t\r\n:-|")


def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")


def is_job_link(title, url):
    title_l = title.lower()
    url_l = url.lower()
    skip = ("privacy", "contact us", "about us", "disclaimer", "sitemap", "login", "home")
    if len(title) < 12 or any(x in title_l for x in skip):
        return False
    job_words = ("recruitment", "recruitment 202", "vacancy", "vacancies", "admit card",
                 "result", "answer key", "notification", "apply online", "jobs", "job",
                 "bharti", "sarkari", "exam", "application", "post")
    return any(word in title_l or word in url_l for word in job_words)


def collect_job_links(source_url, source_name):
    page = get_page(source_url)
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    found, seen_urls = [], set()
    domain = urlparse(source_url).netloc.lower()
    for a in soup.select("a[href]"):
        title = clean_text(a.get_text(" ", strip=True))
        href = urljoin(source_url, a.get("href", "").strip())
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or not title:
            continue
        if parsed.netloc.lower() != domain:
            continue
        if href.rstrip("/") == source_url.rstrip("/") or href in seen_urls:
            continue
        if not is_job_link(title, href):
            continue
        seen_urls.add(href)
        found.append({"title": title, "url": href, "source": source_name})
        if len(found) >= MAX_LINKS_PER_SOURCE:
            break
    logging.info("%s: found %d possible links", source_name, len(found))
    return found


def extract_labeled_value(text, labels):
    for label in labels:
        # Match label followed by optional punctuation and value up to a likely next label/newline.
        pattern = rf"(?:{label})\s*[:：\-]?\s*(.{{1,180}}?)(?=\s+(?:Department|Qualification|Educational Qualification|Age Limit|Last Date|Important Dates|Application Fee|Selection Process|How to Apply|Official Notification|Apply Online|Total Vacancy|Vacancies|Starting Date)\s*[:：\-]|$)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = clean_text(match.group(1))
            if value and value.lower() not in ("click here", "here", "check notification"):
                return value[:180]
    return ""


def extract_detail(job):
    page = get_page(job["url"])
    if not page:
        return job
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = clean_text(soup.get_text(" ", strip=True))
    title_tag = soup.find(["h1", "h2"])
    if title_tag:
        page_title = clean_text(title_tag.get_text(" ", strip=True))
        if len(page_title) >= 8:
            job["title"] = page_title[:220]

    # Extract links by their visible labels; keep only URLs on the page.
    apply_url = ""
    pdf_url = ""
    for a in soup.select("a[href]"):
        label = clean_text(a.get_text(" ", strip=True)).lower()
        href = urljoin(job["url"], a.get("href", "").strip())
        if not href.startswith(("http://", "https://")):
            continue
        if not apply_url and any(x in label for x in ("apply online", "online apply", "apply here", "registration")):
            apply_url = href
        if not pdf_url and (".pdf" in urlparse(href).path.lower() or "notification" in label or "advertisement" in label):
            pdf_url = href

    fields = {
        "department": [r"Department Name", r"Department", r"Organization"],
        "vacancies": [r"Total Vacancies", r"Total Vacancy", r"No\.? of Posts", r"Vacancy Details", r"Total Posts"],
        "qualification": [r"Educational Qualification", r"Qualification", r"Education"],
        "age_limit": [r"Age Limit", r"Age Criteria"],
        "start_date": [r"Starting Date", r"Application Start Date", r"Online Apply Start Date"],
        "last_date": [r"Last Date", r"Last Date to Apply", r"Closing Date", r"Apply Last Date"],
        "fee": [r"Application Fee", r"Exam Fee", r"Fee Details"],
        "selection": [r"Selection Process", r"Mode of Selection"],
    }
    for key, labels in fields.items():
        job[key] = extract_labeled_value(text, labels)

    job["apply_url"] = apply_url
    job["pdf_url"] = pdf_url
    return job


def safe(value, limit=220):
    value = clean_text(str(value or ""))
    return html.escape(value[:limit]) if value else "उपलब्ध नहीं — आधिकारिक नोटिफिकेशन देखें"


def link_line(label, url):
    if url and url.startswith(("https://", "http://")):
        return f'🔗 <b>{label}:</b> <a href="{html.escape(url, quote=True)}">यहाँ क्लिक करें</a>'
    return f"🔗 <b>{label}:</b> उपलब्ध नहीं — आधिकारिक वेबसाइट देखें"


def make_message(job):
    return (
        f"📢 <b>{safe(job.get('title'))}</b>\n\n"
        f"🏢 <b>विभाग:</b> {safe(job.get('department'))}\n"
        f"👥 <b>कुल पद:</b> {safe(job.get('vacancies'))}\n"
        f"🎓 <b>योग्यता:</b> {safe(job.get('qualification'))}\n"
        f"🎂 <b>आयु सीमा:</b> {safe(job.get('age_limit'))}\n"
        f"📅 <b>आवेदन शुरू:</b> {safe(job.get('start_date'))}\n"
        f"⏰ <b>अंतिम तिथि:</b> {safe(job.get('last_date'))}\n"
        f"💳 <b>आवेदन शुल्क:</b> {safe(job.get('fee'))}\n"
        f"📝 <b>चयन प्रक्रिया:</b> {safe(job.get('selection'))}\n\n"
        f"{link_line('ऑनलाइन आवेदन', job.get('apply_url'))}\n"
        f"{link_line('आधिकारिक नोटिफिकेशन / PDF', job.get('pdf_url'))}\n"
        f"🌐 <b>जानकारी का स्रोत:</b> <a href=\"{html.escape(job['url'], quote=True)}\">{html.escape(job.get('source', 'वेबसाइट'))}</a>\n\n"
        + SOCIAL_LINKS
    )


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("GitHub Secrets में TELEGRAM_BOT_TOKEN और TELEGRAM_CHAT_ID सेट करें।")
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        api_url,
        data={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT,
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Telegram API error: HTTP {response.status_code} - {data}")
    logging.info("Telegram message sent.")


def main():
    seen = load_seen()
    new_seen = set(seen)
    candidates = []
    for source_name, source_url in SOURCES:
        candidates.extend(collect_job_links(source_url, source_name))

    sent_count = 0
    for item in candidates:
        url = item["url"]
        if url in seen:
            continue
        details = extract_detail(item)
        message = make_message(details)
        try:
            send_telegram(message)
            new_seen.add(url)
            sent_count += 1
        except Exception as exc:
            logging.error("Could not send %s: %s", url, exc)
            # Do not mark as seen, so it can retry next run.
    save_seen(new_seen)
    logging.info("Finished. New alerts sent: %d", sent_count)


if __name__ == "__main__":
    main()
