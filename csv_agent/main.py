import os
import io
import json
import time
import smtplib
import threading
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, render_template_string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from groq import Groq
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

MEMORY_PATH = "memory.json"
HISTORY_PATH = "history.json"
CONFIG_PATH = "config.json"
TOKEN_PATH = "token.json"
POLL_INTERVAL = 30

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

app = Flask(__name__)
client = Groq(api_key=GROQ_API_KEY)


# ---------- Helpers ----------
def extract_file_id(url):
    if not url:
        return None
    if "/d/" in url:
        part = url.split("/d/")[1]
        return part.split("/")[0]
    return None


def read_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r") as f:
            return json.load(f)
    return []


def read_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {"file_url": "", "file_name": "Not set"}


def save_config(file_url, file_name):
    with open(CONFIG_PATH, "w") as f:
        json.dump({"file_url": file_url, "file_name": file_name}, f)


# ---------- Google Auth ----------
def get_drive_service():
    creds = None
    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = {
                "installed": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(
                prompt="consent",
                access_type="offline",
                login_hint="ramsaiavinash13@gmail.com"
            )
            print("\n👉 Open this URL in your browser:")
            print(auth_url)
            print()
            code = input("Paste the authorization code here: ")
            flow.fetch_token(code=code)
            creds = flow.credentials
        if not os.getenv("GOOGLE_TOKEN_JSON"):
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = {
                "installed": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(
                prompt="consent",
                access_type="offline",
                login_hint="ramsaiavinash13@gmail.com"
            )
            print("\n👉 Open this URL in your browser:")
            print(auth_url)
            print()
            code = input("Paste the authorization code here: ")
            flow.fetch_token(code=code)
            creds = flow.credentials
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


# ---------- Drive ----------
def get_file_modified_time(service, file_id):
    file = service.files().get(
        fileId=file_id,
        fields="modifiedTime,name"
    ).execute()
    return file["modifiedTime"], file["name"]


def download_as_csv(service, file_id):
    request = service.files().export_media(
        fileId=file_id,
        mimeType="text/csv"
    )
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return pd.read_csv(buffer)


# ---------- Memory ----------
def save_snapshot(df, modified_time):
    data = {
        "modified_time": modified_time,
        "data": df.astype(str).to_dict(orient="records")
    }
    with open(MEMORY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def load_snapshot():
    if not os.path.exists(MEMORY_PATH):
        return None, None
    with open(MEMORY_PATH, "r") as f:
        data = json.load(f)
    records = data["data"]
    if not records:
        return pd.DataFrame(), data["modified_time"]
    return pd.DataFrame(records), data["modified_time"]


# ---------- Diff ----------
def compute_diff(old_df, new_df):
    old_rows = set(old_df.astype(str).apply(lambda r: "|".join(r.values), axis=1))
    new_rows = set(new_df.astype(str).apply(lambda r: "|".join(r.values), axis=1))
    added = list(new_rows - old_rows)
    removed = list(old_rows - new_rows)
    return {
        "added": added,
        "removed": removed,
        "columns": list(new_df.columns),
        "total_rows_before": len(old_df),
        "total_rows_after": len(new_df),
    }


# ---------- AI ----------
def ai_analyze(diff, new_df):
    print("AI is analyzing...")
    prompt = f"""
You are an intelligent data monitor agent. A shared Google Sheet has just been updated by a team member.

Columns: {diff['columns']}
Rows before: {diff['total_rows_before']}
Rows after: {diff['total_rows_after']}
Rows added: {json.dumps(diff['added'], indent=2)}
Rows removed: {json.dumps(diff['removed'], indent=2)}

Current data:
{new_df.to_string(index=False)}

Write a clean, short, professional email. Use this exact structure:

SUMMARY: One line saying what changed overall.

CHANGES:
- List each change in one short line

KEY OBSERVATION: One or two lines on any pattern or concern.

ACTION NEEDED: One clear recommendation line.

Keep it under 15 lines. Be direct. No long paragraphs.
"""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )
    return response.choices[0].message.content


# ---------- Email ----------
def send_email(subject, body):
    print(f"Sending email to {NOTIFY_EMAIL}...")
    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, NOTIFY_EMAIL, msg.as_string())
    print("Email sent!")


# ---------- History ----------
def log_history(diff, analysis, filename):
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filename": filename,
        "added": len(diff["added"]),
        "removed": len(diff["removed"]),
        "summary": analysis,
    }
    history = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r") as f:
            history = json.load(f)
    history.insert(0, entry)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


# ---------- Monitor thread ----------
def monitor_loop(service):
    print("Monitor thread started. Watching for changes...")
    last_file_id = None

    while True:
        try:
            file_id = None
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r") as f:
                    cfg = json.load(f)
                file_id = extract_file_id(cfg.get("file_url", ""))

            if not file_id:
                print("No file configured yet. Waiting...")
                time.sleep(POLL_INTERVAL)
                continue

            # Reset snapshot if file changed
            if file_id != last_file_id:
                print(f"New file detected. Resetting snapshot...")
                if os.path.exists(MEMORY_PATH):
                    os.remove(MEMORY_PATH)
                last_file_id = file_id

            print(f"Checking file: {file_id[:20]}...")
            modified_time, filename = get_file_modified_time(service, file_id)
            old_df, last_modified = load_snapshot()

            if old_df is None:
                print("Saving initial snapshot...")
                new_df = download_as_csv(service, file_id)
                save_snapshot(new_df, modified_time)
                print("Snapshot saved. Watching for changes...\n")
            elif modified_time != last_modified:
                print(f"Change detected!")
                new_df = download_as_csv(service, file_id)
                diff = compute_diff(old_df, new_df)
                if diff["added"] or diff["removed"]:
                    analysis = ai_analyze(diff, new_df)
                    send_email(f"CSV Monitor Agent - Changes in {filename}", analysis)
                    log_history(diff, analysis, filename)
                    print("Done.\n")
                save_snapshot(new_df, modified_time)
            else:
                print("No changes.")

        except Exception as e:
            print(f"Monitor error: {e}")

        time.sleep(POLL_INTERVAL)


# ---------- Dashboard ----------
PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Data Monitor Agent</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#f4f7f6; --card:#ffffff; --border:#e3ebe8; --border-2:#d2ded9;
    --ink:#0b1f1a; --ink-2:#4a5f59; --ink-3:#8ba099;
    --teal:#0d9488; --teal-dark:#0f766e; --teal-soft:#ecfdf9; --teal-border:#99f6e4;
    --green:#16a34a; --green-soft:#f0fdf4;
    --red:#dc2626; --red-soft:#fef2f2;
    --amber:#d97706; --amber-soft:#fffbeb;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family:'Inter',-apple-system,Segoe UI,Roboto,sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.55;
    padding:56px 20px; -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:820px; margin:0 auto; }
  .top { display:flex; align-items:center; justify-content:space-between; margin-bottom:40px; }
  .brand { display:flex; align-items:center; gap:14px; }
  .mark {
    width:46px; height:46px; border-radius:13px; background:var(--teal); color:#fff;
    display:flex; align-items:center; justify-content:center;
    font-family:'Space Grotesk'; font-size:24px; font-weight:700;
  }
  .brand h1 { font-family:'Space Grotesk'; font-size:20px; font-weight:600; letter-spacing:-0.02em; }
  .brand .role { font-size:12px; color:var(--ink-3); font-weight:500; }
  .pill {
    display:inline-flex; align-items:center; gap:7px; font-size:12px; font-weight:600;
    color:var(--teal-dark); background:var(--teal-soft); border:1px solid var(--teal-border);
    padding:7px 13px; border-radius:999px;
  }
  .dot { width:7px; height:7px; border-radius:50%; background:var(--teal); animation:pulse 2s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(13,148,136,.4);} 70%{box-shadow:0 0 0 7px rgba(13,148,136,0);} 100%{box-shadow:0 0 0 0 rgba(13,148,136,0);} }
  .hero { font-family:'Space Grotesk'; font-size:38px; line-height:1.15; font-weight:700; letter-spacing:-0.03em; margin-bottom:14px; }
  .hero span { color:var(--teal); }
  .lede { color:var(--ink-2); font-size:16px; max-width:560px; margin-bottom:36px; }
  .tabs { display:flex; gap:4px; background:#e9f0ee; padding:5px; border-radius:12px; width:fit-content; margin-bottom:28px; }
  .tab { font-size:14px; font-weight:600; color:var(--ink-2); text-decoration:none; padding:9px 22px; border-radius:9px; transition:all .15s; }
  .tab.on { background:var(--card); color:var(--teal-dark); box-shadow:0 1px 3px rgba(11,31,26,.08); }
  .card { background:var(--card); border:1px solid var(--border); border-radius:18px; }
  .setup { padding:32px; }
  .setup h2 { font-family:'Space Grotesk'; font-size:18px; font-weight:600; margin-bottom:6px; }
  .setup p { font-size:14px; color:var(--ink-3); margin-bottom:22px; }
  .current-file { display:flex; align-items:center; gap:12px; background:var(--teal-soft); border:1px solid var(--teal-border); border-radius:12px; padding:14px 18px; margin-bottom:22px; }
  .no-file { display:flex; align-items:center; gap:12px; background:var(--amber-soft); border:1px solid #fde68a; border-radius:12px; padding:14px 18px; margin-bottom:22px; }
  .file-icon { font-size:20px; }
  .fname { font-size:14px; font-weight:600; }
  .fstatus { font-size:12px; color:var(--ink-3); margin-top:2px; }
  .current-file .fname { color:var(--teal-dark); }
  .no-file .fname { color:var(--amber); }
  .input-row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  input[type=text] { flex:1; min-width:300px; font-size:14px; color:var(--ink); background:var(--bg); border:1px solid var(--border-2); border-radius:11px; padding:12px 14px; }
  input[type=text]::placeholder { color:var(--ink-3); }
  .btn { background:var(--teal); color:#fff; font-weight:600; border:none; padding:13px 28px; border-radius:11px; font-size:14px; cursor:pointer; white-space:nowrap; transition:filter .15s; }
  .btn:hover { filter:brightness(1.08); }
  .hint { font-size:12px; color:var(--ink-3); margin-top:10px; }
  .hint code { background:var(--border); padding:2px 6px; border-radius:4px; font-size:11px; }
  .flash { padding:14px 18px; border-radius:12px; margin-top:20px; font-size:14px; font-weight:500; border:1px solid; }
  .flash.ok { background:var(--green-soft); border-color:#bbf7d0; color:var(--green); }
  .flash.warn { background:var(--amber-soft); border-color:#fde68a; color:var(--amber); }
  .entry { padding:24px 26px; margin-bottom:16px; }
  .entry-top { display:flex; align-items:center; gap:12px; margin-bottom:18px; flex-wrap:wrap; }
  .ts { font-family:'Space Grotesk'; font-size:15px; font-weight:600; color:var(--ink); }
  .file-badge { font-size:12px; color:var(--teal-dark); background:var(--teal-soft); padding:3px 11px; border-radius:7px; font-weight:600; }
  .chips { display:flex; gap:8px; margin-left:auto; }
  .chip { font-size:13px; font-weight:700; padding:3px 12px; border-radius:8px; font-family:'Space Grotesk'; }
  .chip.add { color:var(--green); background:var(--green-soft); }
  .chip.rem { color:var(--red); background:var(--red-soft); }
  .divider { height:1px; background:var(--border); margin-bottom:18px; }
  .summary { font-size:15px; line-height:1.75; color:var(--ink-2); white-space:pre-wrap; }
  .section { font-size:12px; font-weight:600; color:var(--ink-3); text-transform:uppercase; letter-spacing:.06em; margin-bottom:14px; }
  .empty { text-align:center; color:var(--ink-3); padding:56px 20px; font-size:14px; border:1px dashed var(--border-2); border-radius:18px; background:var(--card); }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand">
      <div class="mark">M</div>
      <div>
        <h1>Data Monitor Agent</h1>
        <div class="role">AI change monitoring</div>
      </div>
    </div>
    <span class="pill"><span class="dot"></span> Active</span>
  </div>
  <div class="hero">Know exactly<br>what <span>changed.</span></div>
  <div class="lede">Paste your Google Sheet URL. The agent watches it automatically and emails you when anything changes.</div>
  <div class="tabs">
    <a href="/" class="tab {{ 'on' if tab == 'monitor' else '' }}">Monitor</a>
    <a href="/logs" class="tab {{ 'on' if tab == 'logs' else '' }}">Change log</a>
  </div>

  {% if tab == 'monitor' %}
  <div class="card setup">
    <h2>Monitored file</h2>
    <p>Paste your Google Sheet URL below. The agent polls it every 30 seconds for changes.</p>
    {% if config.file_url %}
    <div class="current-file">
      <div class="file-icon">📄</div>
      <div class="file-info">
        <div class="fname">{{ config.file_name }}</div>
        <div class="fstatus">Currently being monitored · checks every 30 seconds</div>
      </div>
    </div>
    {% else %}
    <div class="no-file">
      <div class="file-icon">⚠️</div>
      <div class="file-info">
        <div class="fname">No file connected yet</div>
        <div class="fstatus">Paste a Google Sheet URL below to start monitoring</div>
      </div>
    </div>
    {% endif %}
    <form method="POST" action="/set-file">
      <div class="input-row">
        <input type="text" name="file_url" placeholder="https://docs.google.com/spreadsheets/d/..." value="{{ config.file_url }}">
        <button class="btn" type="submit">{{ 'Update file' if config.file_url else 'Start monitoring' }}</button>
      </div>
    </form>
    <div class="hint">Go to your Google Sheet → Share → Copy link → paste here. Make sure the sheet is shared with <code>ramsaiavinash13@gmail.com</code></div>
    {% if message == 'ok' %}
      <div class="flash ok">✅ File connected! Monitoring starts within 30 seconds.</div>
    {% elif message == 'invalid' %}
      <div class="flash warn">⚠️ Invalid URL. Paste the full Google Sheet URL.</div>
    {% endif %}
  </div>

  {% else %}
  {% if history %}
    <div class="section">Change log</div>
    {% for h in history %}
    <div class="card entry">
      <div class="entry-top">
        <span class="ts">{{ h.timestamp }}</span>
        <span class="file-badge">{{ h.filename }}</span>
        <span class="chips">
          <span class="chip add">+{{ h.added }}</span>
          <span class="chip rem">−{{ h.removed }}</span>
        </span>
      </div>
      <div class="divider"></div>
      <div class="summary">{{ h.summary }}</div>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">No changes logged yet. Connect a Google Sheet and wait for the first change.</div>
  {% endif %}
  {% endif %}

</div>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(PAGE, history=read_history(), config=read_config(), message=None, tab="monitor")


@app.route("/logs")
def logs():
    return render_template_string(PAGE, history=read_history(), config=read_config(), message=None, tab="logs")


@app.route("/set-file", methods=["POST"])
def set_file():
    file_url = request.form.get("file_url", "").strip()
    file_id = extract_file_id(file_url)
    if not file_id:
        return render_template_string(PAGE, history=read_history(), config=read_config(), message="invalid", tab="monitor")
    save_config(file_url, f"Sheet — {file_id[:20]}...")
    return render_template_string(PAGE, history=read_history(), config=read_config(), message="ok", tab="monitor")


# ---------- Entry point ----------
if __name__ == "__main__":
    print("Starting CSV Monitor Agent...")
    service = get_drive_service()
    print("Google Drive connected!")

    monitor_thread = threading.Thread(target=monitor_loop, args=(service,), daemon=True)
    monitor_thread.start()

    print("Dashboard starting on port 5000...")
    app.run(host="0.0.0.0", port=5000, debug=False)