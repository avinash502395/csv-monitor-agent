import os
import json
from flask import Flask, render_template_string

app = Flask(__name__)

HISTORY_PATH = "history.json"
CSV_PATH = "sample.csv"

PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CSV Monitor Agent</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 32px; }
  .wrap { max-width: 900px; margin: 0 auto; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .sub { color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
  .status { display: inline-block; background: #16a34a; color: #fff; font-size: 12px; padding: 3px 10px; border-radius: 999px; margin-bottom: 24px; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
  .meta { display: flex; gap: 16px; font-size: 13px; color: #94a3b8; margin-bottom: 12px; flex-wrap: wrap; }
  .badge { background: #334155; padding: 2px 8px; border-radius: 6px; }
  .added { color: #4ade80; } .removed { color: #f87171; } .modified { color: #fbbf24; }
  .summary { white-space: pre-wrap; font-size: 14px; line-height: 1.6; color: #cbd5e1; }
  .time { font-weight: 600; color: #e2e8f0; }
  .empty { text-align: center; color: #64748b; padding: 40px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🤖 CSV Monitor Agent</h1>
  <div class="sub">AI-powered change monitoring for {{ csv }}</div>
  <div class="status">● Agent Active</div>

  {% if history %}
    {% for h in history %}
    <div class="card">
      <div class="meta">
        <span class="time">{{ h.timestamp }}</span>
        <span class="badge added">+{{ h.added }} added</span>
        <span class="badge removed">-{{ h.removed }} removed</span>
        <span class="badge modified">~{{ h.modified }} modified</span>
      </div>
      <div class="summary">{{ h.summary }}</div>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">No changes detected yet. Update the CSV to see AI summaries here.</div>
  {% endif %}
</div>
</body>
</html>
"""


@app.route("/")
def home():
    history = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r") as f:
            history = json.load(f)
    return render_template_string(PAGE, history=history, csv=CSV_PATH)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)