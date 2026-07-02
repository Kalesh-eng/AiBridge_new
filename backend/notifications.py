"""
notifications.py
Email notifications for AIBridge pipeline events.
Uses SMTP (works with Gmail, Outlook, any SMTP server).
Configure in .env file.
"""

import os
import smtplib
from email.mime.text      import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime             import datetime
from dotenv               import load_dotenv

load_dotenv()


def send_email(to: str, subject: str, body_html: str) -> dict:
    """Send an email via SMTP."""
    smtp_host = os.getenv("SMTP_HOST",     "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER",     "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    from_name = os.getenv("SMTP_FROM_NAME","AIBridge")

    if not smtp_user or not smtp_pass:
        print("[Notifications] SMTP not configured — skipping email")
        return {"success": False, "message": "SMTP not configured"}

    try:
        msg              = MIMEMultipart("alternative")
        msg["Subject"]   = subject
        msg["From"]      = f"{from_name} <{smtp_user}>"
        msg["To"]        = to
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to, msg.as_string())

        print(f"[Notifications] Email sent to {to}: {subject}")
        return {"success": True}
    except Exception as e:
        print(f"[Notifications] Email failed: {e}")
        return {"success": False, "message": str(e)}


# ── Email templates ───────────────────────────────────────────────────────────

def notify_pipeline_success(
    to:            str,
    pipeline_name: str,
    rows_loaded:   int,
    duration_s:    int,
    run_id:        str
):
    """Send success notification after pipeline completes."""
    subject = f"✓ Pipeline complete: {pipeline_name}"
    body    = f"""
<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <div style="background:#EAF3DE;border-radius:8px;padding:16px 20px;margin-bottom:16px">
    <h2 style="margin:0;color:#27500A;font-size:16px">✓ Pipeline executed successfully</h2>
  </div>

  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#888;width:140px">Pipeline</td>
      <td style="padding:8px 0;font-weight:500">{pipeline_name}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#888">Rows loaded</td>
      <td style="padding:8px 0;font-weight:500">{rows_loaded:,}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#888">Duration</td>
      <td style="padding:8px 0;font-weight:500">{duration_s}s</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#888">Completed at</td>
      <td style="padding:8px 0;font-weight:500">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;color:#888">Run ID</td>
      <td style="padding:8px 0;font-family:monospace;font-size:11px;color:#888">{run_id}</td>
    </tr>
  </table>

  <div style="margin-top:20px">
    <a href="{os.getenv('APP_URL','http://localhost:5173')}/pipelines"
       style="background:#185FA5;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500">
      View pipeline →
    </a>
  </div>

  <p style="font-size:11px;color:#aaa;margin-top:20px">
    AIBridge — Auto ETL Platform
  </p>
</div>
"""
    return send_email(to, subject, body)


def notify_pipeline_failure(
    to:            str,
    pipeline_name: str,
    error_message: str,
    run_id:        str
):
    """Send failure alert when pipeline errors."""
    subject = f"✗ Pipeline failed: {pipeline_name}"
    body    = f"""
<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <div style="background:#fef2f2;border-radius:8px;padding:16px 20px;margin-bottom:16px">
    <h2 style="margin:0;color:#991b1b;font-size:16px">✗ Pipeline execution failed</h2>
  </div>

  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#888;width:140px">Pipeline</td>
      <td style="padding:8px 0;font-weight:500">{pipeline_name}</td>
    </tr>
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:8px 0;color:#888">Failed at</td>
      <td style="padding:8px 0;font-weight:500">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</td>
    </tr>
    <tr>
      <td style="padding:8px 0;color:#888">Error</td>
      <td style="padding:8px 0;color:#991b1b;font-family:monospace;font-size:11px">{error_message}</td>
    </tr>
  </table>

  <div style="margin-top:20px;display:flex;gap:10px">
    <a href="{os.getenv('APP_URL','http://localhost:5173')}/pipelines"
       style="background:#185FA5;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500">
      View logs →
    </a>
  </div>

  <p style="font-size:11px;color:#aaa;margin-top:20px">
    AIBridge — Auto ETL Platform
  </p>
</div>
"""
    return send_email(to, subject, body)


def notify_signup_welcome(to: str, full_name: str):
    """Welcome email on signup."""
    subject = "Welcome to AIBridge — your AI-powered ETL platform"
    body    = f"""
<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h1 style="font-size:22px;color:#111;margin-bottom:6px">Welcome to AIBridge, {full_name}!</h1>
  <p style="color:#555;font-size:13px;line-height:1.6;margin-bottom:20px">
    You now have access to an AI-powered ETL platform that turns plain English into
    fully automated data pipelines. Here is how to get started in 3 steps.
  </p>

  <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin-bottom:10px">
    <div style="font-size:13px;font-weight:600;margin-bottom:4px">Step 1 — Add your database connection</div>
    <div style="font-size:12px;color:#888">Go to Connectors and add your Postgres, MySQL, or other database.</div>
  </div>

  <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin-bottom:10px">
    <div style="font-size:13px;font-weight:600;margin-bottom:4px">Step 2 — Run the ETL Agent</div>
    <div style="font-size:12px;color:#888">Describe your data in plain English. AI generates schema, model, mappings and SQL.</div>
  </div>

  <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin-bottom:20px">
    <div style="font-size:13px;font-weight:600;margin-bottom:4px">Step 3 — Execute and analyse</div>
    <div style="font-size:12px;color:#888">One click runs the full ETL. Query your warehouse instantly in BI Analytics.</div>
  </div>

  <a href="{os.getenv('APP_URL','http://localhost:5173')}"
     style="background:#185FA5;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500">
    Open AIBridge →
  </a>

  <p style="font-size:11px;color:#aaa;margin-top:24px">
    AIBridge — Where Data Meets AI
  </p>
</div>
"""
    return send_email(to, subject, body)


def notify_password_reset(to: str, reset_token: str):
    """Password reset email."""
    app_url  = os.getenv("APP_URL", "http://localhost:5173")
    reset_url= f"{app_url}/reset-password?token={reset_token}"
    subject  = "Reset your AIBridge password"
    body     = f"""
<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="font-size:18px;color:#111;margin-bottom:8px">Reset your password</h2>
  <p style="color:#555;font-size:13px;line-height:1.6;margin-bottom:20px">
    Click the button below to reset your AIBridge password.
    This link expires in 1 hour.
  </p>

  <a href="{reset_url}"
     style="background:#185FA5;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:500">
    Reset password →
  </a>

  <p style="font-size:11px;color:#aaa;margin-top:24px">
    If you did not request this, ignore this email. Your password will not change.
  </p>
</div>
"""
    return send_email(to, subject, body)
