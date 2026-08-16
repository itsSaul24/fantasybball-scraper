import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

DISCORD_API = "https://discord.com/api/v10"
MAX_MESSAGE_CHARS = 1900  # buffer under Discord's 2000 char message limit

def _chunk_text(text, max_chars=MAX_MESSAGE_CHARS):
    """Split text into <= max_chars pieces, breaking on paragraph boundaries where possible."""
    chunks = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(block) <= max_chars:
            current = block
        else:
            for i in range(0, len(block), max_chars):
                chunks.append(block[i:i + max_chars])
    if current:
        chunks.append(current)
    return chunks

def _post_message(channel_id, token, content):
    res = requests.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        json={"content": content},
        timeout=15,
    )
    res.raise_for_status()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # Discord's limit for non-boosted servers

def send_file(file_path, message=""):
    """Uploads a file to the configured channel. Handy for getting the workbook onto a
    phone without setting up mail."""
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel_id = os.environ["DISCORD_CHANNEL_ID"]
    size = os.path.getsize(file_path)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"{file_path} is {size/1024/1024:.1f} MB — over Discord's 10 MB limit")

    with open(file_path, "rb") as fh:
        res = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            data={"payload_json": json.dumps({"content": message})},
            files={"files[0]": (os.path.basename(file_path), fh)},
            timeout=60,
        )
    res.raise_for_status()
    print(f"✅ Sent {os.path.basename(file_path)} ({size/1024:.0f} KB) to Discord")

def send_notice(text):
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel_id = os.environ["DISCORD_CHANNEL_ID"]
    try:
        _post_message(channel_id, token, text)
    except Exception as e:
        print(f"❌ Failed to send Discord notice: {e}")

def send_digest(waiver_analysis, roster_analysis, cost=None):
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel_id = os.environ["DISCORD_CHANNEL_ID"]
    today = datetime.now().strftime("%B %d, %Y")

    full_text = (
        f"# 🏀 Fantasy BBall Daily Digest — {today}\n\n"
        f"## 📋 Waiver Wire Intelligence\n\n{waiver_analysis}\n\n"
        f"## 🎯 Your Roster Report\n\n{roster_analysis}"
    )

    footer = f"\n\n-# 💰 ${cost:.4f}" if cost is not None else ""
    chunks = _chunk_text(full_text, max_chars=MAX_MESSAGE_CHARS - len(footer))
    chunks = [chunk + footer for chunk in chunks]
    try:
        for chunk in chunks:
            _post_message(channel_id, token, chunk)
        print(f"✅ Digest sent to Discord channel {channel_id} ({len(chunks)} message(s))")
    except Exception as e:
        print(f"❌ Failed to send Discord digest: {e}")
        raise
