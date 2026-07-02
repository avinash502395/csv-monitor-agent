import os
import json
import time
import smtplib
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
CSV_PATH = "sample.csv"
MEMORY_PATH = "memory.json"
HISTORY_PATH = "history.json"

client = Groq(api_key=GROQ_API_KEY)


def save_snapshot(df):
    df.to_json(MEMORY_PATH, orient="records", indent=2)
    print("Snapshot saved to memory.")


def load_snapshot():
    if not os.path.exists(MEMORY_PATH):
        return None
    with open(MEMORY_PATH, "r") as f:
        return pd.DataFrame(json.load(f))


def log_history(diff, analysis):
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "added": len(diff["added"]),
        "removed": len(diff["removed"]),
        "modified": len(diff["modified"]),
        "summary": analysis,
    }
    history = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r") as f:
            history = json.load(f)
    history.insert(0, entry)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)
    print("History logged.")


def compute_diff(old_df, new_df):
    diff = {}
    old_ids = set(old_df["id"].astype(str))
    new_ids = set(new_df["id"].astype(str))
    added_ids = new_ids - old_ids
    removed_ids = old_ids - new_ids
    added = new_df[new_df["id"].astype(str).isin(added_ids)]
    removed = old_df[old_df["id"].astype(str).isin(removed_ids)]
    common_ids = old_ids & new_ids
    modified_rows = []
    for rid in common_ids:
        old_row = old_df[old_df["id"].astype(str) == rid].iloc[0]
        new_row = new_df[new_df["id"].astype(str) == rid].iloc[0]
        changes = {}
        for col in new_df.columns:
            if str(old_row[col]) != str(new_row[col]):
                changes[col] = {"before": str(old_row[col]), "after": str(new_row[col])}
        if changes:
            modified_rows.append({"id": rid, "changes": changes})
    diff["added"] = added.to_dict(orient="records")
    diff["removed"] = removed.to_dict(orient="records")
    diff["modified"] = modified_rows
    diff["total_rows_before"] = len(old_df)
    diff["total_rows_after"] = len(new_df)
    return diff


def ai_analyze(diff, new_df):
    print("AI is analyzing the changes...")
    prompt = f"""
You are an intelligent work monitor agent. A CSV file that tracks work tasks has just been updated.

Here is a summary of what changed:
- Rows before: {diff['total_rows_before']}
- Rows after: {diff['total_rows_after']}
- New rows added: {json.dumps(diff['added'], indent=2)}
- Rows removed: {json.dumps(diff['removed'], indent=2)}
- Rows modified: {json.dumps(diff['modified'], indent=2)}

Current full data:
{new_df.to_string(index=False)}

Write a clean, short, professional email. Use this exact structure:

SUMMARY: One line saying what changed overall.

CHANGES:
- List each change in one short line

STATUS OVERVIEW:
- List each task with owner and current status in one line

RISKS: One or two lines max about anything that needs attention.

ACTION NEEDED: One clear recommendation line.

Keep the whole email under 15 lines. Be direct. No long paragraphs.
"""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )
    return response.choices[0].message.content


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
    print("Email sent successfully!")


def run_agent():
    print("CSV change detected! Running agent...")
    time.sleep(1)
    try:
        new_df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return
    old_df = load_snapshot()
    if old_df is None:
        print("No previous snapshot found. Saving initial snapshot.")
        save_snapshot(new_df)
        return
    diff = compute_diff(old_df, new_df)
    if not diff["added"] and not diff["removed"] and not diff["modified"]:
        print("No meaningful changes detected. Skipping email.")
        return
    analysis = ai_analyze(diff, new_df)
    subject = f"CSV Monitor Agent - Changes Detected in {CSV_PATH}"
    send_email(subject, analysis)
    log_history(diff, analysis)
    save_snapshot(new_df)
    print("Memory updated.")


class CSVChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_triggered = 0

    def on_modified(self, event):
        if event.src_path.endswith("sample.csv"):
            now = time.time()
            if now - self.last_triggered > 2:
                self.last_triggered = now
                run_agent()


if __name__ == "__main__":
    print("CSV Monitor Agent started!")
    print(f"Watching: {CSV_PATH}")
    print("Waiting for changes...\n")
    if not os.path.exists(MEMORY_PATH):
        try:
            df = pd.read_csv(CSV_PATH)
            save_snapshot(df)
            print("Initial snapshot created.\n")
        except Exception as e:
            print(f"Could not read CSV: {e}")
    event_handler = CSVChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nAgent stopped.")
    observer.join()