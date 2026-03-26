import os
import time
import logging
from gmail_poller import poll_gmail
from sms_handler import poll_sms_replies
from scheduler import run_scheduled_tasks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Rim Repair Booking System starting...")
    
    while True:
        try:
            # Poll Gmail for new customer emails
            poll_gmail()
            
            # Check for owner SMS replies (YES/NO/edits)
            poll_sms_replies()
            
            # Run scheduled tasks (reminders, review requests)
            run_scheduled_tasks()
            
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
        
        time.sleep(60)  # Poll every 60 seconds

if __name__ == "__main__":
    main()
