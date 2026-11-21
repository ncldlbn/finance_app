"""Invio delle email dell'app (verifica dell'indirizzo, recupero della password) via SMTP.

Configurazione (variabili d'ambiente):
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD
    SMTP_SECURITY   starttls (predefinito) | ssl | none
    MAIL_FROM       mittente, es. "Finance Tracker <noreply@tuodominio.it>"
    APP_BASE_URL    indirizzo pubblico dell'app (https://...): i link nelle email partono da qui, MAI dall'host
                    della richiesta (che un malintenzionato può falsificare per farsi mandare i link a casa sua).

Senza SMTP_HOST non si spedisce nulla: le email finiscono in OUTBOX (le ultime 50) e nel log. Serve in locale e
nei test; in produzione, senza SMTP, registrazione e recupero password sono spenti (vedi mail_ready in app.py).
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

log = logging.getLogger(__name__)
OUTBOX = []                 # email non spedite (senza SMTP): dict(to, subject, text)
OUTBOX_MAX = 50


class MailError(Exception):
    """L'email non è partita (server non raggiungibile, credenziali sbagliate…)."""


def configured():
    return bool(os.environ.get('SMTP_HOST'))


def base_url():
    return os.environ.get('APP_BASE_URL', '').rstrip('/')


def send(to, subject, text, html=None):
    """Spedisce un'email (testo, più HTML se c'è). Senza SMTP la mette in OUTBOX. MailError se l'invio fallisce."""
    if not configured():
        OUTBOX.append({'to': to, 'subject': subject, 'text': text})
        del OUTBOX[:-OUTBOX_MAX]
        log.warning('Email NON spedita (SMTP non configurato) a %s: %s\n%s', to, subject, text)
        return
    sender = os.environ.get('MAIL_FROM') or os.environ.get('SMTP_USER', '')
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = sender, to, subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain=(sender.rsplit('@', 1)[-1].strip('> ') or None))
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype='html')
    host, port = os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587'))
    security = os.environ.get('SMTP_SECURITY', 'starttls').lower()
    user, password = os.environ.get('SMTP_USER', ''), os.environ.get('SMTP_PASSWORD', '')
    try:
        if security == 'ssl':
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        with server:
            if security == 'starttls':
                server.starttls(context=ssl.create_default_context())
            if user:
                server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        log.error('Invio email a %s non riuscito: %s', to, e)
        raise MailError(str(e)) from e
