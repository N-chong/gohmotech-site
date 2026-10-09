"""
SMS service layer — the single path every outgoing SMS flows through.

``send_sms()`` is deliberately the *only* place that writes an ``SmsLog`` and
talks to a provider client, so every send (Daily / Alert / Reminder / Test) is
logged identically with its provider response, and the enable/recipient rules
are enforced in exactly one place. Tasks and views call this; they never touch a
provider client directly.

SECURITY: provider credentials live only in the client (which reads them from
settings/.env). This layer never sees or logs the API key.
"""

import logging

from .models import SmsLog, SmsSettings
from .providers import get_client, normalize_ph_number

logger = logging.getLogger(__name__)


def send_sms(*, message, sms_type, number=None, notification=None,
             reminder=None, force=False):
    """Send one SMS and record it as an ``SmsLog``.

    Args:
        message: the text body to send.
        sms_type: one of ``SmsLog.SMS_TYPE_CHOICES`` keys (daily/alert/reminder/test).
        number: recipient; falls back to ``SmsSettings.recipient_number``.
        notification: optional ``security.Notification`` this SMS reports on.
        reminder: optional ``SmsReminder`` that triggered this SMS.
        force: when True, skip the master-enabled gate (used by the Test button
               so an operator can verify config before switching SMS on).

    Returns:
        The ``SmsLog`` row (status 'sent' or 'failed'), or ``None`` if sending
        was skipped because the subsystem is disabled.
    """
    settings_obj = SmsSettings.get_config()

    if not force and not settings_obj.enabled:
        logger.info("SMS disabled; skipping %s message", sms_type)
        return None

    recipient = (number or settings_obj.recipient_number or '').strip()

    # Create the log row up front so a failure is always recorded, never silent.
    log = SmsLog.objects.create(
        sms_type=sms_type,
        recipient=recipient,
        message=message,
        status='pending',
        notification=notification,
        reminder=reminder,
    )

    # Validate/normalize the recipient before spending anything.
    try:
        normalized = normalize_ph_number(recipient)
    except ValueError as exc:
        log.mark_failed(error=str(exc))
        logger.warning("SMS to %r not sent: %s", recipient, exc)
        return log

    client = get_client()
    log.mark_sending(provider=getattr(client, 'name', ''))
    logger.info("[SMS] Sending %s SMS log=%s provider=%s", sms_type, log.pk,
                getattr(client, 'name', 'unknown'))
    try:
        result = client.send(normalized, message)
    except Exception as exc:  # Provider failures must never break monitoring.
        safe_error = f"{exc.__class__.__name__}: {exc}"[:500]
        log.mark_failed(error=safe_error,
                        provider=getattr(client, 'name', ''))
        logger.exception("[SMS] Provider error for log=%s", log.pk)
        return log

    if result.ok:
        log.mark_sent(
            provider=result.provider,
            message_id=result.message_id,
            api_response=result.raw,
        )
        logger.info("[SMS] Sent successfully log=%s provider_message_id=%s",
                    log.pk, result.message_id or '-')
    else:
        log.mark_failed(
            error=result.error,
            provider=result.provider,
            api_response=result.raw,
        )
        logger.warning("[SMS] Failed log=%s reason=%s", log.pk,
                       (result.error or 'provider rejected request')[:500])
    return log
