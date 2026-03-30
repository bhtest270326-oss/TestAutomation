JS_MANUAL_BOOKING = """
// ============================================================
// Admin Pro — Manual Booking Section
// ============================================================

function initManualBooking() {
  // Set default date to today
  var dateInput = document.getElementById('mb-preferred-date');
  if (dateInput && !dateInput.value) {
    dateInput.value = new Date().toISOString().split('T')[0];
  }
}

async function createManualBooking(autoConfirm) {
  var name = (document.getElementById('mb-customer-name').value || '').trim();
  var phone = (document.getElementById('mb-phone').value || '').trim();

  if (!name) {
    showToast('Customer name is required', 'error');
    document.getElementById('mb-customer-name').focus();
    return;
  }
  if (!phone) {
    showToast('Phone number is required', 'error');
    document.getElementById('mb-phone').focus();
    return;
  }

  var bookingData = {
    customer_name: name,
    customer_phone: phone,
    customer_email: (document.getElementById('mb-email').value || '').trim(),
    address: (document.getElementById('mb-address').value || '').trim(),
    suburb: (document.getElementById('mb-suburb').value || '').trim(),
    postcode: (document.getElementById('mb-postcode').value || '').trim(),
    vehicle_make: (document.getElementById('mb-vehicle-make').value || '').trim(),
    vehicle_model: (document.getElementById('mb-vehicle-model').value || '').trim(),
    vehicle_colour: (document.getElementById('mb-vehicle-colour').value || '').trim(),
    vehicle_year: (document.getElementById('mb-vehicle-year').value || '').trim(),
    service_type: document.getElementById('mb-service-type').value,
    num_rims: parseInt(document.getElementById('mb-num-rims').value, 10) || 1,
    preferred_date: (document.getElementById('mb-preferred-date').value || '').trim(),
    preferred_time: (document.getElementById('mb-preferred-time').value || '').trim(),
    notes: (document.getElementById('mb-notes').value || '').trim()
  };

  var notify = document.getElementById('mb-notify-customer').checked;

  // Disable buttons while submitting
  var btns = document.querySelectorAll('#manual-booking-form .ap-btn');
  btns.forEach(function(b) { b.disabled = true; });

  try {
    var resp = await apiFetch('/api/manual-bookings/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        booking_data: bookingData,
        auto_confirm: autoConfirm,
        notify: notify
      })
    });

    if (!resp || !resp.ok) {
      showToast((resp && resp.error) || 'Failed to create booking', 'error');
      return;
    }

    var result = resp.data || {};
    var status = result.status || 'unknown';
    var bid = result.booking_id || '';
    var warning = result.warning || '';

    if (warning) {
      showToast('Booking ' + bid + ' created with warning: ' + warning, 'info');
    } else {
      showToast('Booking ' + bid + ' created (' + status + ')', 'success');
    }

    clearManualBookingForm();

  } catch (err) {
    console.error('createManualBooking error:', err);
    showToast('Error creating booking: ' + err.message, 'error');
  } finally {
    btns.forEach(function(b) { b.disabled = false; });
  }
}

function clearManualBookingForm() {
  var form = document.getElementById('manual-booking-form');
  if (form) form.reset();
  initManualBooking(); // Reset defaults
}
"""
