import os
import logging
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar'
]

DEFAULT_JOB_DURATION_MINUTES = 60

def get_calendar_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
        client_id=os.environ['GOOGLE_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
        token_uri='https://oauth2.googleapis.com/token',
        scopes=SCOPES
    )
    return build('calendar', 'v3', credentials=creds)

def create_calendar_event(booking_data):
    """
    Create a Google Calendar event for a confirmed booking.
    Returns event ID or None on failure.
    """
    try:
        service = get_calendar_service()
        
        date_str = booking_data.get('preferred_date')
        time_str = booking_data.get('preferred_time') or '09:00'
        
        if not date_str:
            logger.error("No date in booking data, cannot create calendar event")
            return None
        
        # Parse start datetime
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=DEFAULT_JOB_DURATION_MINUTES)
        
        # Build event title
        customer_name = booking_data.get('customer_name', 'Customer')
        service_type = booking_data.get('service_type', 'rim_repair').replace('_', ' ').title()
        num_rims = booking_data.get('num_rims')
        title = f"{service_type} - {customer_name}"
        if num_rims:
            title += f" (x{num_rims} rims)"
        
        # Build description with all job details tech needs
        vehicle = ' '.join(filter(None, [
            booking_data.get('vehicle_colour'),
            booking_data.get('vehicle_make'),
            booking_data.get('vehicle_model')
        ])) or 'Not specified'
        
        customer_phone = booking_data.get('customer_phone', 'N/A')
        customer_email = booking_data.get('customer_email', 'N/A')
        address = booking_data.get('address') or booking_data.get('suburb', 'TBC')
        notes = booking_data.get('notes', '')
        
        description = f"""JOB DETAILS
===========
Customer: {customer_name}
Phone: {customer_phone}
Email: {customer_email}

Vehicle: {vehicle}
Service: {service_type}{f' x{num_rims} rims' if num_rims else ''}
Address: {address}

Payment: EFTPOS on the day

{f'Notes: {notes}' if notes else ''}"""
        
        event = {
            'summary': title,
            'location': address,
            'description': description,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'Australia/Perth'
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'Australia/Perth'
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 60},
                    {'method': 'popup', 'minutes': 15}
                ]
            }
        }
        
        calendar_id = os.environ['GOOGLE_CALENDAR_ID']
        
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute()
        
        event_id = created_event.get('id')
        logger.info(f"Calendar event created: {event_id} for {title} on {date_str}")
        return event_id
        
    except HttpError as e:
        logger.error(f"Google Calendar API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Calendar event creation error: {e}", exc_info=True)
        return None
