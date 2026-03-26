import os
import json
import logging
import anthropic
from datetime import datetime

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

EXTRACTION_PROMPT = """You are a booking assistant for a mobile rim repair business in Perth, Western Australia.

Extract booking details from the following customer message. Today's date is {today}.

Customer message:
---
{message}
---

Return ONLY a JSON object with this exact structure:
{{
  "customer_name": "string or null",
  "customer_phone": "string or null",
  "vehicle_make": "string or null",
  "vehicle_model": "string or null",
  "vehicle_colour": "string or null",
  "service_type": "rim_repair | paint_touchup | multiple_rims | unknown",
  "num_rims": "integer or null",
  "preferred_date": "YYYY-MM-DD or null",
  "preferred_time": "HH:MM or null",
  "address": "string or null",
  "suburb": "string or null",
  "notes": "string or null",
  "missing_fields": ["list of field names that are missing and required"],
  "confidence": "high | medium | low"
}}

Required fields are: customer_name, address (or suburb), preferred_date, service_type.
customer_phone is required if no email is available.

For preferred_date, interpret relative dates like "tomorrow", "next Tuesday" etc based on today's date.
For preferred_time, if they say "morning" use 09:00, "afternoon" use 13:00, "end of day" use 16:00.

Return ONLY the JSON object, no other text."""

def extract_booking_details(message_body, subject="", customer_email=""):
    """
    Parse customer message with Claude and return structured booking data.
    Returns: (booking_data dict, missing_fields list, needs_clarification bool)
    """
    try:
        today = datetime.now().strftime("%A %d %B %Y")
        
        full_message = message_body
        if subject:
            full_message = f"Subject: {subject}\n\n{message_body}"
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(
                    today=today,
                    message=full_message
                )
            }]
        )
        
        raw = response.content[0].text.strip()
        
        # Strip markdown fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        
        booking_data = json.loads(raw.strip())
        missing_fields = booking_data.pop('missing_fields', [])
        
        # Add customer email to booking data
        if customer_email:
            booking_data['customer_email'] = customer_email
        
        needs_clarification = len(missing_fields) > 0
        
        logger.info(f"Extracted booking: confidence={booking_data.get('confidence')}, missing={missing_fields}")
        
        return booking_data, missing_fields, needs_clarification
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Claude response: {e}")
        return {}, ["all fields - parse error"], True
    except Exception as e:
        logger.error(f"AI extraction error: {e}", exc_info=True)
        return {}, ["all fields - extraction error"], True

def parse_owner_correction(original_booking, correction_text):
    """
    Parse owner's correction SMS and apply to booking data.
    e.g. "change to 11am" or "address is 22 Smith St Balcatta"
    """
    try:
        prompt = f"""The owner of a rim repair business is confirming a booking and wants to make a correction.

Original booking data:
{json.dumps(original_booking, indent=2)}

Owner's correction message:
"{correction_text}"

Apply the correction and return the COMPLETE updated booking JSON with the same structure as the original.
Return ONLY the JSON object, no other text."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        raw = response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        
        updated = json.loads(raw.strip())
        return updated
        
    except Exception as e:
        logger.error(f"Correction parse error: {e}")
        return original_booking

def format_booking_for_owner(booking_data):
    """Format booking data into a clean SMS for owner confirmation."""
    name = booking_data.get('customer_name') or 'Unknown'
    phone = booking_data.get('customer_phone') or booking_data.get('customer_email') or 'N/A'
    vehicle = ' '.join(filter(None, [
        booking_data.get('vehicle_colour'),
        booking_data.get('vehicle_make'),
        booking_data.get('vehicle_model')
    ])) or 'Unknown vehicle'
    
    service = booking_data.get('service_type', 'unknown').replace('_', ' ').title()
    num_rims = booking_data.get('num_rims')
    if num_rims:
        service += f" x{num_rims}"
    
    date = booking_data.get('preferred_date') or 'TBC'
    time = booking_data.get('preferred_time') or 'TBC'
    address = booking_data.get('address') or booking_data.get('suburb') or 'TBC'
    notes = booking_data.get('notes')
    
    msg = f"""NEW BOOKING REQUEST
Name: {name}
Contact: {phone}
Vehicle: {vehicle}
Service: {service}
Date: {date} at {time}
Address: {address}"""
    
    if notes:
        msg += f"\nNotes: {notes}"
    
    msg += "\n\nReply YES to confirm, NO to decline, or send corrections (e.g. 'change time to 11am')"
    
    return msg
