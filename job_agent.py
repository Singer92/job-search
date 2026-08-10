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
    raw = f"{norm}|{(title or '').strip().lower()}|{(company or '').strip().
