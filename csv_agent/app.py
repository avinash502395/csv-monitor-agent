import os
import json
import smtplib
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, redirect, render_template_string

load_dotenv()

HISTORY_PATH = "history.json"
CONFIG_PATH = "config.json"

app = Flask(__name__)


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


def extract_file_id(url):
    if "/d/" in url:
        part = url.split("/d/")[1]
        file_id = part.split("/")[0]
        return file_id
    return None


PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CSV Monitor Agent</title>
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
  .tab {
    font-size:14px; font-weight:600; color:var(--ink-2); text-decoration:none;
    padding:9px 22px; border-radius:9px; transition:all .15s;
  }
  .tab.on { background:var(--card); color:var(--teal-dark); box-shadow:0 1px 3px rgba(11,31,26,.08); }
  .card { background:var(--card); border:1px solid var(--border); border-radius:18px; }

  /* Monitor setup */
  .setup { padding:32px; }
  .setup h2 { font-family:'Space Grotesk'; font-size:18px; font-weight:600; margin-bottom:6px; }
  .setup p { font-size:14px; color:var(--ink-3); margin-bottom:22px; }
  .current-file {
    display:flex; align-items:center; gap:12px;
    background:var(--teal-soft); border:1px solid var(--teal-border);
    border-radius:12px; padding:14px 18px; margin-bottom:22px;
  }
  .file-icon { font-size:20px; }
  .file-info { flex:1; }
  .file-info .fname { font-size:14px; font-weight:600; color:var(--teal-dark); }
  .file-info .fstatus { font-size:12px; color:var(--ink-3); margin-top:2px; }
  .no-file {
    display:flex; align-items:center; gap:12px;
    background:var(--amber-soft); border:1px solid #fde68a;
    border-radius:12px; padding:14px 18px; margin-bottom:22px;
  }
  .no-file .fname { font-size:14px; font-weight:600; color:var(--amber); }
  .no-file .fstatus { font-size:12px; color:var(--ink-3); margin-top:2px; }
  .input-row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  input[type=text] {
    flex:1; min-width:300px; font-size:14px; color:var(--ink);
    background:var(--bg); border:1px solid var(--border-2);
    border-radius:11px; padding:12px 14px;
  }
  input[type=text]::placeholder { color:var(--ink-3); }
  .btn {
    background:var(--teal); color:#fff; font-weight:600; border:none;
    padding:13px 28px; border-radius:11px; font-size:14px; cursor:pointer;
    white-space:nowrap; transition:filter .15s;
  }
  .btn:hover { filter:brightness(1.08); }
  .hint { font-size:12px; color:var(--ink-3); margin-top:10px; }
  .hint code { background:var(--border); padding:2px 6px; border-radius:4px; font-size:11px; }

  /* Flash */
  .flash { padding:14px 18px; border-radius:12px; margin-top:20px; font-size:14px; font-weight:500; border:1px solid; }
  .flash.ok { background:var(--green-soft); border-color:#bbf7d0; color:var(--green); }
  .flash.warn { background:var(--amber-soft); border-color:#fde68a; color:var(--amber); }

  /* Log */
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
        <h1>CSV Monitor Agent</h1>
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
    <p>Paste your Google Sheet URL below. The agent polls it every 2 minutes for changes.</p>

    {% if config.file_url %}
    <div class="current-file">
      <div class="file-icon">📄</div>
      <div class="file-info">
        <div class="fname">{{ config.file_name }}</div>
        <div class="fstatus">Currently being monitored · updates every 2 minutes</div>
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
    <div class="hint">Go to your Google Sheet → click Share → Copy link → paste it here. Make sure the sheet is shared with <code>ramsaiavinash13@gmail.com</code></div>

    {% if message == 'ok' %}
      <div class="flash ok">✅ File connected! The agent will start monitoring it within 2 minutes.</div>
    {% elif message == 'invalid' %}
      <div class="flash warn">⚠️ Invalid URL. Make sure you paste the full Google Sheet URL.</div>
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

    # Update .env with new file ID
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("GOOGLE_FILE_ID="):
            lines[i] = f"GOOGLE_FILE_ID={file_id}\n"
            updated = True
    if not updated:
        lines.append(f"GOOGLE_FILE_ID={file_id}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

    return render_template_string(PAGE, history=read_history(), config=read_config(), message="ok", tab="monitor")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)