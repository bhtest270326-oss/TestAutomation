import logging
import time
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5-minute TTL for label cache entries

# Label definitions with Gmail colour codes
# Gmail background/text colour pairs (from Gmail API colour palette)
LABELS = {
    'Pending Reply': {
        'color': {'backgroundColor': '#fb4c2f', 'textColor': '#ffffff'},  # Red - awaiting customer info
        'description': 'Customer contacted, awaiting more info from them'
    },
    'Awaiting Confirmation': {
        'color': {'backgroundColor': '#ffad47', 'textColor': '#ffffff'},  # Orange - sent to owner
        'description': 'Booking details extracted, awaiting owner YES/NO'
    },
    'Confirmed': {
        'color': {'backgroundColor': '#16a766', 'textColor': '#ffffff'},  # Green - confirmed
        'description': 'Booking confirmed, calendar event created'
    },
    'Declined': {
        'color': {'backgroundColor': '#8e63ce', 'textColor': '#ffffff'},  # Purple - declined
        'description': 'Booking declined by owner'
    },
    'Processed': {
        'color': {'backgroundColor': '#999999', 'textColor': '#ffffff'},  # Grey - catch-all processed
        'description': 'Email has been processed by the booking system'
    },
    'Assistance Required': {
        'color': {'backgroundColor': '#4a86e8', 'textColor': '#ffffff'},  # Blue - owner attention needed
        'description': 'Customer asked an off-scope question — draft reply created for owner review'
    },
}

_label_cache = {}  # Maps label_name -> (label_id, timestamp)


def clear_label_cache():
    """Clear the entire label cache, forcing fresh lookups on next access."""
    _label_cache.clear()
    logger.info("Label cache cleared")


def get_or_create_label(service, label_name):
    """Get or create a Gmail label by name, with colour. Returns label ID or None."""
    if label_name in _label_cache:
        cached_id, cached_time = _label_cache[label_name]
        if time.time() - cached_time < CACHE_TTL_SECONDS:
            return cached_id
        # TTL expired — discard stale entry and re-fetch
        del _label_cache[label_name]
        logger.debug(f"Cache TTL expired for label '{label_name}', re-fetching")

    try:
        result = service.users().labels().list(userId='me').execute()
        existing = {l['name']: l['id'] for l in result.get('labels', [])}

        if label_name in existing:
            _label_cache[label_name] = (existing[label_name], time.time())
            return existing[label_name]

        # Create with colour if defined
        body = {
            'name': label_name,
            'labelListVisibility': 'labelShow',
            'messageListVisibility': 'show',
        }

        if label_name in LABELS and 'color' in LABELS[label_name]:
            body['color'] = LABELS[label_name]['color']

        try:
            created = service.users().labels().create(userId='me', body=body).execute()
            label_id = created['id']
        except HttpError as e:
            if e.resp.status == 409:
                # Another request created the label concurrently — re-fetch to get the ID
                result2 = service.users().labels().list(userId='me').execute()
                existing2 = {l['name']: l['id'] for l in result2.get('labels', [])}
                label_id = existing2.get(label_name)
                if not label_id:
                    logger.error(f"Label '{label_name}' 409 but still not found after re-fetch")
                    return None
            else:
                raise
        _label_cache[label_name] = (label_id, time.time())
        logger.info(f"Created label: {label_name}")
        return label_id

    except HttpError as e:
        logger.error(f"Label create error for '{label_name}': {e}")
        _label_cache.pop(label_name, None)
        return None
    except Exception as e:
        logger.error(f"Label error for '{label_name}': {e}")
        _label_cache.pop(label_name, None)
        return None

def apply_label(service, msg_id, label_name, remove_labels=None):
    """Apply a label to a message, optionally removing others.

    Raises on failure so callers can handle errors appropriately.
    On 404 from messages().modify(), retries once after clearing the stale cache entry.
    """
    add_id = get_or_create_label(service, label_name)
    if not add_id:
        raise RuntimeError(f"Could not get or create label '{label_name}'")

    remove_ids = []
    if remove_labels:
        for rl in remove_labels:
            rid = get_or_create_label(service, rl)
            if rid:
                remove_ids.append(rid)

    try:
        service.users().messages().modify(
            userId='me',
            id=msg_id,
            body={
                'addLabelIds': [add_id],
                'removeLabelIds': remove_ids
            }
        ).execute()
    except HttpError as e:
        if e.resp.status == 404:
            # Label ID may be stale — clear cache entry and retry once
            logger.warning(f"Got 404 applying label '{label_name}', retrying with fresh lookup")
            _label_cache.pop(label_name, None)
            add_id = get_or_create_label(service, label_name)
            if not add_id:
                raise
            service.users().messages().modify(
                userId='me',
                id=msg_id,
                body={
                    'addLabelIds': [add_id],
                    'removeLabelIds': remove_ids
                }
            ).execute()
        else:
            raise

    logger.info(f"Applied label '{label_name}' to message {msg_id}")

def initialise_labels(service):
    """Pre-create all labels on startup so they appear in Gmail sidebar."""
    for label_name in LABELS:
        get_or_create_label(service, label_name)

def label_pending_reply(service, msg_id):
    """Red — we asked customer for more info, waiting on them."""
    apply_label(service, msg_id, 'Pending Reply',
                remove_labels=['Awaiting Confirmation', 'Confirmed', 'Declined', 'Processed'])

def label_awaiting_confirmation(service, msg_id):
    """Orange — booking extracted, sent to owner for YES/NO."""
    apply_label(service, msg_id, 'Awaiting Confirmation',
                remove_labels=['Pending Reply', 'Confirmed', 'Declined', 'Processed'])

def label_confirmed(service, msg_id):
    """Green — owner confirmed, calendar event created. Archived out of inbox."""
    apply_label(service, msg_id, 'Confirmed',
                remove_labels=['Pending Reply', 'Awaiting Confirmation', 'Declined', 'Processed'])
    # Archive — remove from inbox so it sits in the Confirmed label folder
    try:
        service.users().messages().modify(
            userId='me',
            id=msg_id,
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        logger.info(f"Archived message {msg_id} from inbox (filed under Confirmed)")
    except Exception as e:
        logger.error(f"Archive error for message {msg_id}: {e}")

def label_declined(service, msg_id):
    """Purple — owner declined."""
    apply_label(service, msg_id, 'Declined',
                remove_labels=['Pending Reply', 'Awaiting Confirmation', 'Confirmed', 'Processed'])

def label_processed(service, msg_id):
    """Grey — processed, no action needed."""
    apply_label(service, msg_id, 'Processed',
                remove_labels=['Pending Reply', 'Awaiting Confirmation', 'Confirmed', 'Declined'])


def label_assistance_required(service, msg_id):
    """Blue — customer asked an off-scope question; a draft reply has been created for owner review."""
    apply_label(service, msg_id, 'Assistance Required',
                remove_labels=['Pending Reply', 'Awaiting Confirmation', 'Confirmed', 'Declined', 'Processed'])
