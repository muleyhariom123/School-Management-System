// School Management System - Main Interactive Logic

document.addEventListener('DOMContentLoaded', function () {
  // 1. Sidebar mobile toggle
  const sidebar = document.querySelector('.sidebar');
  const toggleBtn = document.getElementById('sidebarToggleBtn');
  const backdrop = document.getElementById('sidebarBackdrop');

  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', function () {
      sidebar.classList.toggle('show');
      if (backdrop) backdrop.classList.toggle('show');
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', function () {
      sidebar.classList.remove('show');
      backdrop.classList.remove('show');
    });
  }

  // 2. Dynamic Section -> Class -> Class Section cascading dropdowns
  const sectionSelect = document.getElementById('school_section_id');
  const classSelect = document.getElementById('class_id');
  const classSectionSelect = document.getElementById('class_section_id');

  if (sectionSelect && classSelect) {
    sectionSelect.addEventListener('change', function () {
      const sectionId = this.value;
      if (!sectionId) return;

      fetch(`/admin/api/classes-by-section/${sectionId}`)
        .then(res => res.json())
        .then(classes => {
          classSelect.innerHTML = '<option value="">-- Select Class --</option>';
          classes.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name;
            classSelect.appendChild(opt);
          });
          if (classSectionSelect) {
            classSectionSelect.innerHTML = '<option value="">-- Select Section --</option>';
          }
        })
        .catch(err => console.error('Error fetching classes:', err));
    });
  }

  if (classSelect && classSectionSelect) {
    classSelect.addEventListener('change', function () {
      const classId = this.value;
      if (!classId) return;

      fetch(`/admin/api/sections-by-class/${classId}`)
        .then(res => res.json())
        .then(sections => {
          classSectionSelect.innerHTML = '<option value="">-- Select Section --</option>';
          sections.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = s.section_name;
            classSectionSelect.appendChild(opt);
          });
        })
        .catch(err => console.error('Error fetching sections:', err));
    });
  }

  // 3. Dynamic Fee Payment Modal: Load student fee items & outstanding balance
  const paymentStudentSelect = document.getElementById('payment_student_select');
  const paymentFeeAssignmentSelect = document.getElementById('payment_fee_assignment_select');
  const outstandingDisplay = document.getElementById('student_outstanding_display');
  const amountInput = document.getElementById('payment_amount_input');

  if (paymentStudentSelect) {
    paymentStudentSelect.addEventListener('change', function () {
      const studentId = this.value;
      if (!studentId) {
        if (outstandingDisplay) outstandingDisplay.innerHTML = '';
        if (paymentFeeAssignmentSelect) paymentFeeAssignmentSelect.innerHTML = '<option value="">-- General Fee Payment --</option>';
        return;
      }

      fetch(`/admin/api/student-fees/${studentId}`)
        .then(res => res.json())
        .then(data => {
          if (paymentFeeAssignmentSelect) {
            paymentFeeAssignmentSelect.innerHTML = '<option value="">-- General / Combined Fee Payment --</option>';
            data.items.forEach(item => {
              const opt = document.createElement('option');
              opt.value = item.assignment_id;
              opt.textContent = `${item.fee_category} (Due: $${item.remaining.toFixed(2)})`;
              opt.dataset.remaining = item.remaining;
              paymentFeeAssignmentSelect.appendChild(opt);
            });
          }

          if (outstandingDisplay && data.summary) {
            const bal = data.summary.outstanding_balance;
            const balColor = bal > 0 ? 'text-danger' : 'text-success';
            outstandingDisplay.innerHTML = `
              <div class="alert ${bal > 0 ? 'alert-warning' : 'alert-success'} py-2 px-3 mb-3 d-flex justify-content-between align-items-center">
                <span><b>Total Outstanding:</b></span>
                <span class="fs-5 fw-bold ${balColor}">$${bal.toFixed(2)}</span>
              </div>
            `;
            if (amountInput && bal > 0 && !amountInput.value) {
              amountInput.value = bal.toFixed(2);
            }
          }
        })
        .catch(err => console.error('Error fetching student fee data:', err));
    });
  }

  // 4. Client-side Instant Filter for Tables
  const tableSearchInput = document.getElementById('tableQuickSearch');
  if (tableSearchInput) {
    tableSearchInput.addEventListener('input', function () {
      const term = this.value.toLowerCase();
      const rows = document.querySelectorAll('.filterable-table tbody tr');
      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
      });
    });
  }

  // 5. Bulk attendance helper buttons
  window.markAllAttendance = function (status) {
    const radios = document.querySelectorAll(`input[type="radio"][value="${status}"]`);
    radios.forEach(r => {
      r.checked = true;
    });
  };

  // 6. Auto dismiss alerts after 6 seconds
  setTimeout(() => {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(al => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(al);
      if (bsAlert) bsAlert.close();
    });
  }, 6000);
});
