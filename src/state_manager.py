import json
import os
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STATE_FILE = os.environ.get('STATE_FILE', '/data/booking_state.json')

class StateManager:
    def __init__(self):
        self._ensure_state_file()
    
    def _ensure_state_file(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        if not os.path.exists(STATE_FILE):
            self._write_state({
                'pending_bookings': {},
                'confirmed_bookings': {},
                'processed_emails': [],
                'processed_sms': []
            })
    
    def _read_state(self):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"State read error: {e}")
            return {
                'pending_bookings': {},
                'confirmed_bookings': {},
                'processed_emails': [],
                'processed_sms': []
            }
    
    def _write_state(self, state):
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"State write error: {e}")
    
    def create_pending_booking(self, booking_data, source, customer_email=None, raw_message=None, msg_id=None, thread_id=None):
        """Create a pending booking awaiting owner confirmation."""
        state = self._read_state()
        pending_id = str(uuid.uuid4())[:8].upper()
        
        state['pending_bookings'][pending_id] = {
            'id': pending_id,
            'booking_data': booking_data,
            'source': source,
            'customer_email': customer_email,
            'raw_message': raw_message,
            'gmail_msg_id': msg_id,
            'thread_id': thread_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'status': 'awaiting_owner'
        }
        
        self._write_state(state)
        logger.info(f"Created pending booking {pending_id}")
        return pending_id
    
    def get_pending_booking(self, pending_id):
        state = self._read_state()
        return state['pending_bookings'].get(pending_id)
    
    def get_latest_pending_booking(self):
        """Get the most recent pending booking awaiting owner reply."""
        state = self._read_state()
        pending = [
            b for b in state['pending_bookings'].values()
            if b['status'] == 'awaiting_owner'
        ]
        if not pending:
            return None
        return sorted(pending, key=lambda x: x['created_at'], reverse=True)[0]
    
    def confirm_booking(self, pending_id, booking_data=None):
        """Move booking from pending to confirmed."""
        state = self._read_state()
        pending = state['pending_bookings'].get(pending_id)
        if not pending:
            return False
        
        if booking_data:
            pending['booking_data'] = booking_data
        
        pending['status'] = 'confirmed'
        pending['confirmed_at'] = datetime.now(timezone.utc).isoformat()
        
        state['confirmed_bookings'][pending_id] = pending
        del state['pending_bookings'][pending_id]
        
        self._write_state(state)
        logger.info(f"Confirmed booking {pending_id}")
        return True
    
    def decline_booking(self, pending_id):
        """Mark booking as declined."""
        state = self._read_state()
        pending = state['pending_bookings'].get(pending_id)
        if not pending:
            return False
        
        pending['status'] = 'declined'
        pending['declined_at'] = datetime.now(timezone.utc).isoformat()
        
        state['confirmed_bookings'][pending_id] = pending
        del state['pending_bookings'][pending_id]
        
        self._write_state(state)
        return True
    
    def update_booking_calendar_event(self, pending_id, event_id):
        """Store Google Calendar event ID against confirmed booking."""
        state = self._read_state()
        if pending_id in state['confirmed_bookings']:
            state['confirmed_bookings'][pending_id]['calendar_event_id'] = event_id
            self._write_state(state)
    
    def mark_reminder_sent(self, booking_id, reminder_type):
        """Track which reminders have been sent."""
        state = self._read_state()
        booking = state['confirmed_bookings'].get(booking_id)
        if booking:
            if 'reminders_sent' not in booking:
                booking['reminders_sent'] = []
            booking['reminders_sent'].append({
                'type': reminder_type,
                'sent_at': datetime.now(timezone.utc).isoformat()
            })
            self._write_state(state)
    
    def has_reminder_been_sent(self, booking_id, reminder_type):
        state = self._read_state()
        booking = state['confirmed_bookings'].get(booking_id)
        if not booking:
            return False
        reminders = booking.get('reminders_sent', [])
        return any(r['type'] == reminder_type for r in reminders)
    
    def get_confirmed_bookings(self):
        state = self._read_state()
        return state['confirmed_bookings']

    def get_confirmed_bookings_for_date(self, date_str):
        """Return list of booking_data dicts for confirmed bookings on a given date."""
        state = self._read_state()
        result = []
        for booking in state['confirmed_bookings'].values():
            if booking.get('status') != 'confirmed':
                continue
            bd = booking.get('booking_data', {})
            if bd.get('preferred_date') == date_str:
                result.append(bd)
        return result
    
    def is_email_processed(self, msg_id):
        state = self._read_state()
        return msg_id in state.get('processed_emails', [])
    
    def mark_email_processed(self, msg_id):
        state = self._read_state()
        if 'processed_emails' not in state:
            state['processed_emails'] = []
        if msg_id not in state['processed_emails']:
            state['processed_emails'].append(msg_id)
            # Keep list manageable
            if len(state['processed_emails']) > 1000:
                state['processed_emails'] = state['processed_emails'][-500:]
        self._write_state(state)
    
    def is_sms_processed(self, sms_sid):
        state = self._read_state()
        return sms_sid in state.get('processed_sms', [])
    
    def mark_sms_processed(self, sms_sid):
        state = self._read_state()
        if 'processed_sms' not in state:
            state['processed_sms'] = []
        if sms_sid not in state['processed_sms']:
            state['processed_sms'].append(sms_sid)
            if len(state['processed_sms']) > 1000:
                state['processed_sms'] = state['processed_sms'][-500:]
        self._write_state(state)

    def create_pending_clarification(self, booking_data, customer_email, thread_id, msg_id, missing_fields):
        """Store partial booking data while waiting for customer to provide missing info."""
        state = self._read_state()
        if 'pending_clarifications' not in state:
            state['pending_clarifications'] = {}
        
        clarification_id = str(uuid.uuid4())[:8].upper()
        state['pending_clarifications'][clarification_id] = {
            'id': clarification_id,
            'booking_data': booking_data,
            'customer_email': customer_email,
            'thread_id': thread_id,
            'gmail_msg_id': msg_id,
            'missing_fields': missing_fields,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        self._write_state(state)
        return clarification_id

    def get_pending_booking_by_thread(self, thread_id):
        """Find a pending clarification by Gmail thread ID.

        Only checks pending_clarifications — if the thread already has a complete
        pending booking or confirmed booking we treat any new message as a fresh
        enquiry rather than risk creating duplicate bookings.
        """
        state = self._read_state()
        for item in state.get('pending_clarifications', {}).values():
            if item.get('thread_id') == thread_id:
                return item
        return None

    def thread_has_active_booking(self, thread_id):
        """Return True if the thread already has a pending or confirmed booking
        (i.e. past the clarification stage) so we can skip duplicate processing."""
        state = self._read_state()
        for item in state.get('pending_bookings', {}).values():
            if item.get('thread_id') == thread_id:
                return True
        for item in state.get('confirmed_bookings', {}).values():
            if item.get('thread_id') == thread_id:
                return True
        return False

    def update_clarification_booking_data(self, clarification_id, booking_data, missing_fields):
        """Update partial booking data for an ongoing clarification."""
        state = self._read_state()
        if 'pending_clarifications' not in state:
            return
        if clarification_id in state['pending_clarifications']:
            state['pending_clarifications'][clarification_id]['booking_data'] = booking_data
            state['pending_clarifications'][clarification_id]['missing_fields'] = missing_fields
            self._write_state(state)

    def remove_pending_clarification(self, clarification_id):
        """Remove a clarification record once all data is collected."""
        state = self._read_state()
        if 'pending_clarifications' in state:
            state['pending_clarifications'].pop(clarification_id, None)
            self._write_state(state)
