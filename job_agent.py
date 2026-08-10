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
            time.sleep(1) # Respect rate limits
    return jobs

def fetch_jooble(cfg, session, limit):
    api_key = os.getenv("JOUBLE_API_KEY")
    if not api_key or not cfg.get("sources", {}).get("jooble", {}).get("enabled"):
        return []
        
    jobs = []
    queries = cfg.get("search_queries", [])
    url = f"https://jooble.org/api/{api_key}"

    for query in queries:
        payload = {"keyword": query, "location": "", "page": 1}
        try:
            r = session.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                for item in r.json().get("jobs", [])[:limit]:
                    title = item.get("title", "")
                    company = item.get("company", "")
                    location = item.get("location", "")
                    snippet = strip_html(item.get("snippet", ""))
                    link = item.get("link", "")
                    jobs.append({
                        "title": title, "company": company, "location": location,
                        "remote": is_remote_text(f"{title} {location} {snippet}"),
                        "url": link, "source": "jooble", "posted_date": item.get("published", ""), "description": snippet
                    })
        except Exception as e:
            logging.warning(f"Jooble error for {query}: {e}")
        time.sleep(1)
    return jobs

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
    model = os.getenv
