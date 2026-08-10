import os
import re
import json
import time
import hashlib
import logging
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlsplit, parse_qsl, urlencode

import requests
import yaml
import feedparser
from openai import OpenAI

# Setup logging for GitHub Actions
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DB_PATH = "jobs.db"

def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def normalize_url(url):
    if not url: return ""
    parts = urlsplit(url)
    keep_params = {"id", "jobid", "job_id", "job", "jid"}
    qs = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() in keep_params]
    query = urlencode(qs)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{query}" if query else "")

def make_job_id(url, title, company):
    norm = normalize_url(url)
    raw = f"{norm}|{(title or '').strip().lower()}|{(company or '').strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, remote INTEGER,
        url TEXT UNIQUE, source TEXT, posted_date TEXT, description TEXT,
        first_seen TEXT, last_seen TEXT, status TEXT DEFAULT 'new',
        match_score INTEGER, should_apply TEXT, match_json TEXT, cover_letter TEXT
    )""")
    return conn

def job_exists(conn, job_id):
    return conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is not None

def save_job(conn, job, result):
    conn.execute("""
    INSERT OR IGNORE INTO jobs (id, title, company, location, remote, url, source, posted_date, description, first_seen, last_seen, status, match_score, should_apply, match_json, cover_letter)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job.get("id"), job.get("title", ""), job.get("company", ""), job.get("location", ""), int(bool(job.get("remote", False))),
        normalize_url(job.get("url", "")), job.get("source", ""), job.get("posted_date", ""), (job.get("description") or "")[:20000],
        datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), "new",
        int(result.get("match_score", 0)), result.get("should_apply", "no"), json.dumps(result, ensure_ascii=False), result.get("cover_letter", "")
    ))
    conn.execute("""
    UPDATE jobs SET last_seen = ?, match_score = ?, should_apply = ?, match_json = ?, cover_letter = ? WHERE id = ?
    """, (datetime.now(timezone.utc).isoformat(), int(result.get("match_score", 0)), result.get("should_apply", "no"), json.dumps(result, ensure_ascii=False), result.get("cover_letter", ""), job.get("id")))

def is_remote_text(text):
    text = (text or "").lower()
    return any(k in text for k in ["remote", "work from home", "online", "virtual", "wfh"])

def strip_html(text):
    if not text: return ""
    text = re.sub(r"<[^<]+?>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# --- SOURCE 1: ADZUNA API (Global/Private) ---
def fetch_adzuna(cfg, session, limit):
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key or not cfg.get("sources", {}).get("adzuna", {}).get("enabled"):
        return []
    
    jobs = []
    countries = cfg["sources"]["adzuna"].get("countries", [])
    queries = cfg.get("search_queries", [])
    max_days_old = cfg.get("agent", {}).get("max_days_old", 4)

    for country in countries:
        for query in queries:
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            params = {"app_id": app_id, "app_key": app_key, "what": query, "results_per_page": limit, "max_days_old": max_days_old}
            try:
                r = session.get(url, params=params, timeout=30)
                if r.status_code == 200:
                    for item in r.json().get("results", []):
                        title = item.get("title", "")
                        company = item.get("company", "")
                        if isinstance(company, dict): company = company.get("display_name", "")
                        location = item.get("location", "")
                        if isinstance(location, dict): location = location.get("display_name", "")
                        description = strip_html(item.get("description", ""))
                        link = item.get("redirect_url") or item.get("url") or ""
                        jobs.append({
                            "title": title, "company": company, "location": location,
                            "remote": is_remote_text(f"{title} {location} {description}"),
                            "url": link, "source": f"adzuna:{country}", "posted_date": item.get("created", ""), "description": description
                        })
            except Exception as e:
                logging.warning(f"Adzuna error for {country}/{query}: {e}")
            time.sleep(1)
    return jobs

# --- SOURCE 2: RSS FEEDS (Employment News / Academic) ---
def fetch_rss_feeds(cfg, session):
    rss_cfg = cfg.get("sources", {}).get("rss", {})
    if not rss_cfg.get("enabled"): return []
    
    jobs = []
    for feed in rss_cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries[:10]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = strip_html(entry.get("summary", ""))
                text = f"{title} {summary}".lower()
                if any(k in text for k in ["music", "isai", "carnatic", "lecturer", "fine arts", "kalakshetra", "sangeet"]):
                    jobs.append({
                        "title": title, "company": feed.get("name", "RSS"), "location": "India",
                        "remote": False, "url": link, "source": f"rss:{feed.get('name')}",
                        "posted_date": entry.get("published", ""), "description": summary
                    })
        except Exception as e:
            logging.warning(f"RSS error for {feed.get('name')}: {e}")
    return jobs

# --- SOURCE 3: TN GOV SCRAPER (TRB / Kalakshetra) ---
def fetch_tn_gov_jobs(session):
    jobs = []
    targets = [
        {"name": "TRB TN", "url": "http://trb.tn.gov.in/"},
        {"name": "Kalakshetra Foundation", "url": "https://www.kalakshetra.org/careers/"}
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    
    for target in targets:
        try:
            r = session.get(target["url"], headers=headers, timeout=15)
            if r.status_code == 200:
                links = re.findall(r'href=[\'"]?([^\'" >]+)', r.text)
                for link in links:
                    lower_link = link.lower()
                    if any(k in lower_link for k in ["music", "isai", "lecturer", "fine_arts", "carnatic", "vocal"]):
                        if link.startswith("/"):
                            link = target["url"].rstrip("/") + link
                        
                        title = link.split("/")[-1].replace("-", " ").replace(".pdf", "").title() or f"Music Vacancy at {target['name']}"
                        
                        jobs.append({
                            "title": f"Govt Music Vacancy: {title}",
                            "company": target["name"],
                            "location": "Tamil Nadu, India",
                            "remote": False,
                            "url": link if link.startswith("http") else target["url"],
                            "source": "tn_gov_scraper",
                            "posted_date": datetime.now(timezone.utc).isoformat(),
                            "description": f"Direct recruitment notification found on {target['name']} portal. Please check the official PDF/website for exact eligibility, age limit, and application dates."
                        })
        except Exception as e:
            logging.warning(f"TN Gov Scraper error for {target['name']}: {e}")
    
    unique_jobs = {j['url']: j for j in jobs}.values()
    return list(unique_jobs)

# --- AI MATCHING ENGINE (Groq/Llama 3) ---
def parse_json_loose(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start >= 0 and end > start: text = text[start:end]
    return json.loads(text)

def call_llm_json(prompt):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key: raise RuntimeError("OPENAI_API_KEY missing.")
    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
    model = os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile")
    messages = [
        {"role": "system", "content": "You are a precise job-matching engine. Return only valid JSON."},
        {"role": "user", "content": prompt}
    ]
    try:
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1, response_format={"type": "json_object"})
    except Exception:
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1)
    return parse_json_loose(resp.choices[0].message.content)

def build_prompt(job, cfg, min_score):
    candidate = cfg.get("candidate", {})
    preferences = cfg.get("preferences", {})
    job_copy = dict(job)
    max_chars = cfg.get("agent", {}).get("max_description_chars", 6000)
    job_copy["description"] = (job_copy.get("description") or "")[:max_chars]
    
    return f"""
You are a global job-search agent for Ezhilarasi Murugesan.
CANDIDATE PROFILE:
{json.dumps(candidate, indent=2, ensure_ascii=False)}
SEARCH PREFERENCES:
{json.dumps(preferences, indent=2, ensure_ascii=False)}
JOB:
{json.dumps(job_copy, indent=2, ensure_ascii=False)}

TASK: Evaluate how well this job matches the candidate.
RULES:
1. Prioritise Carnatic music, Indian classical music, vocal pedagogy, music education, curriculum design, online music teaching, ethnomusicology, teaching artist, and composer/vocalist roles.
2. The candidate is open to remote work, India roles, and relocation.
3. For roles requiring relocation outside India, only consider them strong if the job description explicitly mentions visa sponsorship, work permit support, relocation support, or international hiring. If no such evidence exists, set visa_sponsorship_evidence to "no" or "unclear" and keep match_score at or below 60.
4. For India-based or remote roles, visa sponsorship is not required.
5. Do not invent requirements or benefits.
6. If the role is clearly irrelevant, give a low score.
7. Write a concise tailored cover letter only if match_score is likely at least {min_score}; otherwise return an empty string.

RETURN ONLY VALID JSON WITH THIS SHAPE:
{{
  "match_score": 0,
  "should_apply": "yes",
  "relocation_required": false,
  "visa_sponsorship_evidence": "yes",
  "fit_reasons": ["..."],
  "gaps": ["..."],
  "resume_keywords": ["..."],
  "cover_letter_angle": "...",
  "cover_letter": "..."
}}
""".strip()

def match_job(job, cfg):
    min_score = cfg.get("agent", {}).get("min_match_score", 65)
    prompt = build_prompt(job, cfg, min_score)
    result = call_llm_json(prompt)
    
    try: score = int(result.get("match_score", 0))
    except: score = 0
    score = max(0, min(100, score))
    result["match_score"] = score
    
    relocation = result.get("relocation_required", False)
    if isinstance(relocation, str): relocation = relocation.strip().lower() in {"true", "yes", "1"}
    result["relocation_required"] = bool(relocation)
    
    visa = str(result.get("visa_sponsorship_evidence", "unclear")).strip().lower()
    if visa not in {"yes", "no", "unclear"}: visa = "unclear"
    result["visa_sponsorship_evidence"] = visa
    
    if (cfg.get("preferences", {}).get("visa_sponsorship_required_for_relocation", True)
        and result.get("relocation_required") and result.get("visa_sponsorship_evidence") != "yes"):
        result["match_score"] = min(result["match_score"], 60)
        
    if result["match_score"] < min_score: result["cover_letter"] = ""
    return result

# --- EMAIL DELIVERY ---
def send_email(jobs, cfg):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    to_addr = os.getenv("EMAIL_TO")
    from_addr = os.getenv("EMAIL_FROM") or user
    
    if not all([host, user, password, to_addr]):
        logging.warning("Email secrets missing. Skipping email delivery.")
        return
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"Music Job Digest — {now} — {len(jobs)} matches"
    
    rows = []
    details = []
    for i, job in enumerate(jobs, 1):
        title = job.get("title", "Untitled")
        company = job.get("company", "")
        location = job.get("location", "")
        url = job.get("url", "#")
        score = int(job.get("match_score", 0))
        should = job.get("should_apply", "maybe")
        
        rows.append(f"<tr><td>{i}</td><td><a href='{url}'>{title}</a></td><td>{company}</td><td>{location}</td><td>{score}</td><td>{should}</td></tr>")
        
        fit_items = "".join(f"<li>{x}</li>" for x in job.get("fit_reasons", []))
        gap_items = "".join(f"<li>{x}</li>" for x in job.get("gaps", []))
        kw_items = ", ".join(job.get("resume_keywords", []))
        cover = (job.get("cover_letter", "") or "").replace("\n", "<br>")
        
        details.append(f"""
        <hr>
        <h3>{i}. {title} — {company}</h3>
        <p><strong>Location:</strong> {location} | <strong>Score:</strong> {score} | <strong>Apply?</strong> {should}</p>
        <p><strong>Why it fits:</strong></p><ul>{fit_items or '<li>N/A</li>'}</ul>
        <p><strong>Gaps:</strong></p><ul>{gap_items or '<li>N/A</li>'}</ul>
        <p><strong>Resume keywords:</strong> {kw_items or 'N/A'}</p>
        <p><strong>Draft cover letter:</strong></p>
        <div style="white-space:pre-wrap; background:#f7f7f7; padding:10px; border-radius:6px;">{cover or 'N/A'}</div>
        """)
        
    html_body = f"""
    <html><body>
      <h2>Music Job Search Digest</h2>
      <p>Generated: {now}</p>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <tr style="background-color: #f2f2f2;"><th>#</th><th>Job</th><th>Company</th><th>Location</th><th>Score</th><th>Apply?</th></tr>
        {''.join(rows)}
      </table>
      {''.join(details)}
    </body></html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))
    
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port)
        else:
            server = smtplib.SMTP(host, port)
            server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
        server.quit()
        logging.info(f"Email sent successfully to {to_addr}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

# --- MAIN EXECUTION ---
def main():
    logging.info("Starting Live Job Agent...")
    cfg = load_config()
    conn = init_db()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; MusicJobAgent/1.0)"})
    
    # Enable sources dynamically for live run
    if "adzuna" in cfg.get("sources", {}): cfg["sources"]["adzuna"]["enabled"] = True
    if "jooble" in cfg.get("sources", {}): cfg["sources"]["jooble"]["enabled"] = True
    if "rss" in cfg.get("sources", {}): cfg["sources"]["rss"]["enabled"] = True
    
    fetch_limit = cfg.get("agent", {}).get("max_jobs_to_fetch_per_source", 25)
    
    fetched = []
    fetched.extend(fetch_adzuna(cfg, session, fetch_limit))
    fetched.extend(fetch_rss_feeds(cfg, session))
    fetched.extend(fetch_tn_gov_jobs(session))
    logging.info(f"Fetched {len(fetched)} raw jobs.")
    
    new_jobs = []
    for job in fetched:
        if not job.get("url") or not job.get("title"): continue
        job_id = make_job_id(job["url"], job["title"], job.get("company", ""))
        job["id"] = job_id
        if job_exists(conn, job_id):
            conn.execute("UPDATE jobs SET last_seen = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), job_id))
            continue
        new_jobs.append(job)
        
    max_match = cfg.get("agent", {}).get("max_jobs_to_match", 50)
    new_jobs = new_jobs[:max_match]
    logging.info(f"New jobs to match: {len(new_jobs)}")
    
    matched = []
    min_score = cfg.get("agent", {}).get("min_match_score", 65)
    
    for job in new_jobs:
        try:
            result = match_job(job, cfg)
            save_job(conn, job, result)
            if result.get("match_score", 0) >= min_score:
                job.update(result)
                matched.append(job)
        except Exception as e:
            logging.error(f"Error matching job {job.get('title')}: {e}")
        time.sleep(2) # Sleep to respect Groq free tier rate limits
        
    conn.commit()
    matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)

    # --- GENERATE DASHBOARD DATA (jobs.json) ---
    # We prepare a clean list for the index.html to read
    dashboard_data = []
    for job in matched:
        dashboard_data.append({
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "url": job.get("url"),
            "source": job.get("source"),
            "posted_date": job.get("posted_date"),
            "remote": job.get("remote", False),
            "match_score": job.get("match_score"),
            "should_apply": job.get("should_apply"),
            "fit_reasons": job.get("fit_reasons", []),
            "gaps": job.get("gaps", []),
            "cover_letter": job.get("cover_letter", "")
        })
    
    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)
    logging.info("Saved jobs.json for GitHub Pages dashboard.")

    if not matched:
        logging.info("No new jobs above the match threshold.")
    else:
        logging.info(f"Found {len(matched)} matching jobs. Sending email...")
        send_email(matched, cfg)

if __name__ == "__main__":
    main()
