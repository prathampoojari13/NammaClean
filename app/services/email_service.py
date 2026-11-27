"""
Email service for NammaClean transactional and OTP notifications.
Integrates standard SMTP with TLS support, honest delivery status, and graceful non-blocking execution.
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send_smtp_sync(to_email: str, subject: str, html_body: str, text_body: str) -> Tuple[bool, str]:
    """
    Synchronous SMTP dispatch. Run in a background thread via asyncio.to_thread.
    """
    if not settings.SMTP_HOST:
        logger.info(
            "[EmailService] SMTP_HOST not configured. Email to %s skipped (simulated delivery in dev).",
            to_email,
        )
        return False, "SMTP server is not configured in this environment."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings.SMTP_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)

        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

        server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())
        server.quit()
        logger.info("[EmailService] Successfully sent email to %s via %s", to_email, settings.SMTP_HOST)
        return True, "Email delivered successfully via SMTP."
    except Exception as exc:
        logger.warning("[EmailService] Failed to deliver email to %s: %s", to_email, str(exc))
        return False, f"SMTP delivery failed: {str(exc)}"


async def send_attendance_otp_email(to_email: str, otp: str, expiry_minutes: int = 5) -> Tuple[bool, str]:
    """
    Dispatches a single-use attendance verification OTP to the worker's registered email.
    """
    subject = f"NammaClean — Attendance Verification Code: {otp}"
    text_body = (
        f"Namaskara,\n\n"
        f"Your single-use attendance verification code is: {otp}\n\n"
        f"This code will expire in {expiry_minutes} minutes. Please do not share this code with anyone.\n\n"
        f"Bruhat Bengaluru Mahanagara Palike (BBMP) — NammaClean Portal"
    )
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>NammaClean Attendance Code</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F5F9F5; padding: 24px;">
      <div style="max-width: 500px; margin: 0 auto; background-color: #FFFFFF; border-radius: 12px; border: 1px solid #D5E3D7; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
        <div style="background-color: #183B2A; padding: 20px 24px; text-align: center;">
          <h1 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 750; letter-spacing: -0.02em;">NammaClean</h1>
          <p style="color: #74C69D; margin: 4px 0 0 0; font-size: 13px;">BBMP Civic Workforce Attendance</p>
        </div>
        <div style="padding: 28px 24px; text-align: center;">
          <p style="color: #2F3E35; font-size: 15px; margin: 0 0 16px 0;">Your single-use roll-call attendance verification code is:</p>
          <div style="display: inline-block; background-color: #E8F5E9; border: 2px dashed #2E7D32; border-radius: 8px; padding: 12px 28px; margin: 0 auto 20px auto;">
            <span style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #1B5E20; font-family: monospace;">{otp}</span>
          </div>
          <p style="color: #5A7565; font-size: 13px; margin: 0 0 8px 0;">This code is valid for <strong>{expiry_minutes} minutes</strong> and can only be used once.</p>
          <p style="color: #94A3B8; font-size: 12px; margin: 0;">If you did not request this attendance verification code, please inform your Ward Supervisor immediately.</p>
        </div>
        <div style="background-color: #F8FAF8; padding: 14px 24px; border-top: 1px solid #E2E8F0; text-align: center;">
          <p style="color: #64748B; font-size: 11px; margin: 0;">Govt of Karnataka • Bruhat Bengaluru Mahanagara Palike (BBMP)</p>
        </div>
      </div>
    </body>
    </html>
    """
    return await asyncio.to_thread(_send_smtp_sync, to_email, subject, html_body, text_body)
