import smtplib
import os
import markdown
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def send_digest(waiver_analysis, roster_analysis):
    gmail = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    today = datetime.now().strftime("%B %d, %Y")

    waiver_html = markdown.markdown(waiver_analysis)
    roster_html = markdown.markdown(roster_analysis)

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: auto; padding: 20px; color: #222;">
        <h1 style="color: #1a73e8;">🏀 Fantasy BBall Daily Digest</h1>
        <p style="color: #666;">{today}</p>
        <hr>

        <h2 style="color: #e87d1a;">📋 Waiver Wire Intelligence</h2>
        <div style="background: #f9f9f9; padding: 15px; border-radius: 8px;">
            {waiver_html}
        </div>

        <br>
        <h2 style="color: #1ae87d;">🎯 Your Roster Report</h2>
        <div style="background: #f9f9f9; padding: 15px; border-radius: 8px;">
            {roster_html}
        </div>

        <br>
        <hr>
        <p style="color: #aaa; font-size: 12px;">Generated from r/fantasybball • Powered by Gemini Flash</p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏀 Fantasy BBall Digest — {today}"
    msg["From"] = gmail
    msg["To"] = gmail
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail, password)
            server.sendmail(gmail, gmail, msg.as_string())
        print(f"✅ Digest sent to {gmail}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        raise