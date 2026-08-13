"""smtp — split from import_export.py."""
from ._common import *  # noqa

def _smtp_send_attachments(subject, body, attachments):
    settings_obj = Settings.query.first()
    recipients = [x.email for x in StaffEmail.query.filter_by(is_active=True).all() if x.email]
    if not recipients:
        return False, 'No active staff emails configured in Notifications.'

    smtp_host = (settings_obj.smtp_host if settings_obj and settings_obj.smtp_host else os.environ.get('SMTP_HOST', '')).strip()
    smtp_user = (settings_obj.smtp_user if settings_obj and settings_obj.smtp_user else os.environ.get('SMTP_USER', '')).strip()
    smtp_pass = (settings_obj.smtp_pass if settings_obj and settings_obj.smtp_pass else os.environ.get('SMTP_PASS', '')).strip().replace(' ', '')
    smtp_port = int((settings_obj.smtp_port if settings_obj and settings_obj.smtp_port else os.environ.get('SMTP_PORT', '587')) or 587)
    if settings_obj and settings_obj.smtp_use_tls is not None:
        use_tls = bool(settings_obj.smtp_use_tls)
    else:
        use_tls = os.environ.get('SMTP_USE_TLS', '1').strip() != '0'
    from_email = (
        (settings_obj.smtp_from if settings_obj and settings_obj.smtp_from else '') or
        os.environ.get('SMTP_FROM', '') or
        smtp_user
    ).strip()

    if not smtp_host or not from_email:
        return False, 'SMTP settings missing. Configure in Settings first.'
    if smtp_user and not smtp_pass:
        return False, 'SMTP password missing. Enter SMTP App Password in Settings.'

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = ', '.join(recipients)
    msg.set_content(body)
    for fname, mime, content in attachments:
        maintype, subtype = mime.split('/', 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=fname)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                if use_tls:
                    server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, f'Sent to {len(recipients)} staff email(s).'
    except smtplib.SMTPAuthenticationError as e:
        detail = ''
        try:
            detail = (e.smtp_error or b'').decode(errors='ignore').strip()
        except Exception:
            detail = str(e)
        return False, f'SMTP login failed. {detail}'
    except Exception as e:
        return False, f'SMTP send failed: {e}'


