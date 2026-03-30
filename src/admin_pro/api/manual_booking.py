"""
admin_pro/api/manual_booking.py — Manual booking creation API.
"""
import json
import logging
from datetime import datetime, timezone

from flask import request, jsonify
from state_manager import StateManager, _get_conn

logger = logging.getLogger(__name__)


def register(bp, require_auth):
    """Register manual booking API routes on *bp*."""

    @bp.route('/api/manual-bookings/create', methods=['POST'])
    @require_auth
    def create_manual_booking():
        body = request.get_json(silent=True)
        if not body:
            return jsonify({'ok': False, 'error': 'Request body required'}), 400

        booking_data = body.get('booking_data', {})
        auto_confirm = body.get('auto_confirm', False)
        notify = body.get('notify', False)

        # Validate required fields
        name = booking_data.get('customer_name', '').strip()
        phone = booking_data.get('customer_phone', '').strip()
        if not name:
            return jsonify({'ok': False, 'error': 'Customer name is required'}), 400
        if not phone:
            return jsonify({'ok': False, 'error': 'Customer phone is required'}), 400

        state = StateManager()

        # Create pending booking
        booking_id = state.create_pending_booking(
            booking_data=booking_data,
            source='manual',
            customer_email=booking_data.get('customer_email')
        )

        if auto_confirm and booking_data.get('preferred_date'):
            success = state.confirm_booking(booking_id, booking_data)
            if not success:
                return jsonify({'ok': True, 'data': {
                    'booking_id': booking_id,
                    'status': 'awaiting_owner',
                    'warning': 'Created but could not auto-confirm (possible time conflict)'
                }})

            # Create Google Calendar event
            try:
                from calendar_handler import create_calendar_event
                from maps_handler import get_job_duration_minutes
                duration = get_job_duration_minutes(booking_data)
                event_id = create_calendar_event(booking_id, booking_data, duration)
                if event_id:
                    state.update_booking_calendar_event(booking_id, event_id)
            except Exception:
                logger.exception("Manual booking: calendar event creation failed (non-blocking)")

            # Notify customer if requested
            if notify and booking_data.get('customer_email'):
                try:
                    from admin_pro.api.bookings import _notify_customer_confirmed
                    _notify_customer_confirmed(booking_id, booking_data,
                                               booking_data['customer_email'], None)
                except Exception:
                    logger.exception("Manual booking: customer notification failed (non-blocking)")

            status = 'confirmed'
        else:
            status = 'awaiting_owner'

        # Broadcast SSE event
        try:
            from webhook_server import broadcast_event
            broadcast_event('booking_update', {'booking_id': booking_id, 'action': 'created'})
        except Exception:
            pass

        return jsonify({'ok': True, 'data': {
            'booking_id': booking_id,
            'status': status
        }})


# Self-registration
from admin_pro import admin_pro_bp, require_auth  # noqa: E402
register(admin_pro_bp, require_auth)
