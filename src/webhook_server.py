"""
webhook_server.py — Flask HTTP server for real-time event delivery.

Endpoints:
  POST /webhook/gmail          — Google Pub/Sub push for new Gmail messages
  POST /webhook/twilio/sms     — Twilio inbound SMS from the owner
  GET  /health                 — Railway health check
"""

import os
import json
import base64
import logging
from flask import Flask, request, jsonify

logger = logging.getLogger(__name__)

_PUBSUB_TOKEN = os.environ.get('PUBSUB_WEBHOOK_TOKEN', '')


def create_app():
    app = Flask(__name__)

    from admin_ui import admin_bp
    app.register_blueprint(admin_bp)

    # ------------------------------------------------------------------
    # Gmail / Pub/Sub webhook
    # ------------------------------------------------------------------

    @app.route('/webhook/gmail', methods=['POST'])
    def gmail_webhook():
        # Optional token check — set PUBSUB_WEBHOOK_TOKEN in Railway to enable
        if _PUBSUB_TOKEN:
            if request.args.get('token') != _PUBSUB_TOKEN:
                logger.warning("Gmail webhook: invalid or missing token")
                return 'Unauthorized', 403

        envelope = request.get_json(silent=True)
        if not envelope:
            return 'Bad Request: expected JSON', 400

        pubsub_message = envelope.get('message', {})
        data_b64 = pubsub_message.get('data', '')
        if not data_b64:
            # Pub/Sub sometimes sends an empty keepalive — acknowledge and ignore
            return 'OK', 200

        try:
            notification = json.loads(base64.b64decode(data_b64).decode('utf-8'))
        except Exception as e:
            logger.error(f"Gmail webhook: failed to decode Pub/Sub message: {e}")
            return 'Bad Request: decode failed', 400

        history_id = notification.get('historyId')
        if not history_id:
            return 'OK', 200

        logger.info(f"Gmail webhook: historyId={history_id}")

        try:
            from gmail_poller import process_history_notification
            process_history_notification(history_id)
        except Exception as e:
            logger.error(f"Gmail webhook processing error: {e}", exc_info=True)
            # Return 200 anyway — returning 4xx/5xx causes Pub/Sub to retry

        return 'OK', 200

    # ------------------------------------------------------------------
    # Twilio inbound SMS webhook
    # ------------------------------------------------------------------

    @app.route('/webhook/twilio/sms', methods=['POST'])
    def twilio_sms_webhook():
        # Validate Twilio signature to reject spoofed requests
        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(os.environ['TWILIO_AUTH_TOKEN'])
            signature = request.headers.get('X-Twilio-Signature', '')
            # Use the public URL if behind a proxy (Railway sets X-Forwarded-Proto)
            url = request.url.replace('http://', 'https://', 1)
            if not validator.validate(url, request.form.to_dict(), signature):
                logger.warning("Twilio webhook: invalid signature")
                return 'Unauthorized', 403
        except Exception as e:
            logger.warning(f"Twilio signature validation skipped: {e}")

        from_number = request.form.get('From', '')
        body_text = request.form.get('Body', '')
        message_sid = request.form.get('MessageSid', '')

        if not message_sid:
            return 'Bad Request', 400

        logger.info(f"Twilio webhook: SMS from {from_number} SID={message_sid}")

        try:
            from twilio_handler import process_single_sms_webhook
            process_single_sms_webhook(from_number, body_text, message_sid)
        except Exception as e:
            logger.error(f"Twilio webhook processing error: {e}", exc_info=True)

        # Return empty TwiML — Twilio requires a valid XML response
        return (
            '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            200,
            {'Content-Type': 'text/xml'}
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({'status': 'ok'})

    @app.route('/health/ai', methods=['GET'])
    def health_ai():
        """Diagnostic endpoint — tests whether the Anthropic API is reachable."""
        try:
            from ai_parser import client
            resp = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply with the single word OK"}]
            )
            return jsonify({'status': 'ok', 'response': resp.content[0].text.strip()})
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error_type': type(e).__name__,
                'error': str(e)
            }), 500

    return app
