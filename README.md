# Vinayak Sarkari Job Telegram Bot

यह bot `sarkariresult.com.cm` और `freejobalert.com` पर उपलब्ध संभावित नई job/recruitment posts खोजकर Telegram पर भेजने के लिए बनाया गया है। GitHub Actions पर चलने के कारण आपका laptop बंद होने पर भी scheduled workflow चल सकता है।

## Telegram setup

1. Telegram में `@BotFather` खोलें और `/newbot` से bot बनाएं।
2. BotFather से मिला token सुरक्षित रखें।
3. जिस Telegram channel/group में alerts चाहिए, bot को admin बनाएं (कम से कम messages post करने की permission दें)।
4. `TELEGRAM_CHAT_ID` में channel username जैसे `@your_channel` या numeric chat ID डालें।

## GitHub setup

अपने repository में **Settings → Secrets and variables → Actions → New repository secret** पर ये दो secrets बनाएं:

- `TELEGRAM_BOT_TOKEN` — BotFather token
- `TELEGRAM_CHAT_ID` — Telegram channel username (जैसे `@your_channel`) या numeric chat ID

फिर repository में इस ZIP के files upload/replace करें और `.github/workflows/job-alerts.yml` भी commit करें।

## Run and test

1. GitHub → **Actions** खोलें।
2. **Sarkari Job Telegram Alerts** workflow चुनें।
3. **Run workflow** दबाएं।
4. Green tick आए तो run सफल हुआ; red cross पर run खोलकर logs देखें।

Workflow दिन में तीन बार scheduled है (UTC cron 03:30, 09:30, 15:30; यानी लगभग 09:00, 15:00, 21:00 IST). GitHub schedule exact minute पर चलने की guarantee नहीं देता।

## Message fields

Bot recruitment title, department, vacancies, qualification, age limit, start date, last date, fee, selection process, apply link, notification/PDF link और आपके WhatsApp/Telegram community links भेजने की कोशिश करता है।

**महत्वपूर्ण:** वेबसाइटों का HTML बदल सकता है। कुछ fields source page पर साफ label में न हों तो message में “उपलब्ध नहीं — आधिकारिक नोटिफिकेशन देखें” दिखेगा। Bot missing facts खुद से नहीं बनाता। Apply/PDF link page पर उपलब्ध link labels से पहचाने जाते हैं; हर post में official PDF मिलना guaranteed नहीं है। आवेदन से पहले official notification ज़रूर जांचें।

## Duplicate control

`seen_jobs.json` भेजे जा चुके URLs को रखता है। Workflow इसे repository में commit करता है ताकि अगले scheduled run में वही URL बार-बार न भेजा जाए। Repository Settings → Actions → General में workflow read/write permissions blocked हों तो `GITHUB_TOKEN` को contents write access देने की जरूरत पड़ सकती है.

## Files

- `job_bot.py` — scraping, field extraction, Telegram messages
- `requirements.txt` — Python dependencies
- `.github/workflows/job-alerts.yml` — schedule and cloud execution
- `seen_jobs.json` — sent URLs history (starts empty)

## Security

Token को Python file में न लिखें और public repository में कभी commit न करें। केवल GitHub Secrets में रखें।
