import os
import io
import json
import time
import smtplib
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
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
GOOGLE_FILE_ID = os.getenv("GOOGLE_FILE_ID")

MEMORY_PATH = "memory.json"
HISTORY_PATH = "history.json"
TOKEN_PATH = "token.json"
POLL_INTERVAL = 30  # seconds

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

client = Groq(api_key=GROQ_API_KEY)


# ---------- Google Auth ----------
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
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
            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
            auth_url, _ = flow.authorization_url(
                prompt='consent',
                access_type='offline',
                login_hint='ramsaiavinash13@gmail.com'
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


# ---------- Get file modified time ----------
def get_file_modified_time(service):
    file = service.files().get(
        fileId=GOOGLE_FILE_ID,
        fields="modifiedTime,name"
    ).execute()
    return file["modifiedTime"], file["name"]


# ---------- Download CSV from Google Sheets ----------
def download_as_csv(service):
    request = service.files().export_media(
        fileId=GOOGLE_FILE_ID,
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
    print("Snapshot saved.")


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
You are an intelligent data monitor agent. A shared Google Sheet CSV has just been updated by a team member.

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


# ---------- Main Agent Loop ----------
def run():
    print("Google Drive CSV Monitor Agent started!")
    print(f"Watching file ID: {GOOGLE_FILE_ID}")
    print(f"Polling every {POLL_INTERVAL} seconds...\n")

    service = get_drive_service()
    print("Google Drive connected!")

    while True:
        try:
            modified_time, filename = get_file_modified_time(service)
            old_df, last_modified = load_snapshot()

            if old_df is None:
                print("No snapshot found. Saving initial snapshot...")
                new_df = download_as_csv(service)
                save_snapshot(new_df, modified_time)
                print("Initial snapshot saved. Watching for changes...\n")
            elif modified_time != last_modified:
                print(f"Change detected at {modified_time}!")
                new_df = download_as_csv(service)
                diff = compute_diff(old_df, new_df)
                if diff["added"] or diff["removed"]:
                    analysis = ai_analyze(diff, new_df)
                    send_email(f"CSV Monitor Agent - Changes in {filename}", analysis)
                    log_history(diff, analysis, filename)
                    save_snapshot(new_df, modified_time)
                    print("Done. Watching for next change...\n")
                else:
                    save_snapshot(new_df, modified_time)
                    print("File touched but no row changes. Skipping email.")
            else:
                print(f"No changes. Next check in {POLL_INTERVAL}s...")

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()