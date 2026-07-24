// ---- TABS ----
document.querySelectorAll('.tabs-container').forEach(container => {
    container.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            container.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            container.querySelectorAll('.tab-panel').forEach(p => {
                p.classList.toggle('active', p.dataset.panel === target);
            });
            // Resize Plotly charts in the newly visible tab.
            // display:none prevents ResizeObserver from firing, so we do it explicitly.
            if (typeof Plotly !== 'undefined') {
                const panel = container.querySelector(`.tab-panel[data-panel="${target}"]`);
                if (panel) setTimeout(() => {
                    panel.querySelectorAll('[id^="chart-"]').forEach(el => {
                        if (el.data) Plotly.Plots.resize(el);
                    });
                }, 0);
            }
        });
    });
});

// ---- EXPANDERS ----
document.querySelectorAll('.expander-toggle').forEach(toggle => {
    toggle.addEventListener('click', () => {
        const body = toggle.nextElementSibling;
        const icon = toggle.querySelector('.expander-icon');
        body.classList.toggle('open');
        if (icon) icon.textContent = body.classList.contains('open') ? 'expand_less' : 'expand_more';
    });
});

// ---- AUTO-HIDE FLASH ----
setTimeout(() => {
    document.querySelectorAll('.flash').forEach(el => {
        el.style.transition = 'opacity 0.4s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 400);
    });
}, 3500);

// ---- TOAST ----
function showToast(msg, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    const icon = document.createElement('span');
    icon.className = 'material-icons-round';
    icon.textContent = type === 'success' ? 'check_circle' : 'error_outline';
    toast.appendChild(icon);
    toast.appendChild(document.createTextNode(msg));
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 2600);
}

// ---- EDIT MODALS ----
// Editing happens in a modal opened by the "edit" button of each row, instead
// of inline in the table. The button carries the row values as data-* attrs.
function openModal(modal) {
    if (modal) modal.classList.add('open');
}
function closeModal(modal) {
    if (modal) modal.classList.remove('open');
}

// Fill and open the expense modal.
document.querySelectorAll('.js-edit-expense').forEach(btn => {
    btn.addEventListener('click', () => {
        const modal = document.getElementById('modal-expense');
        const form = document.getElementById('form-edit-expense');
        form.action = btn.dataset.action;
        form.date.value = btn.dataset.date;
        form.euro.value = btn.dataset.euro;
        form.category.value = btn.dataset.category;
        form.description.value = btn.dataset.description;
        openModal(modal);
    });
});

// Fill and open the income modal.
document.querySelectorAll('.js-edit-income').forEach(btn => {
    btn.addEventListener('click', () => {
        const modal = document.getElementById('modal-income');
        const form = document.getElementById('form-edit-income');
        form.action = btn.dataset.action;
        form.date.value = btn.dataset.date;
        form.euro.value = btn.dataset.euro;
        form.description.value = btn.dataset.description;
        openModal(modal);
    });
});

// Fill and open the patrimonio modal (all fields carried as data-* attrs;
// each modal input is set from the matching data attribute by name).
document.querySelectorAll('.js-edit-patrimonio').forEach(btn => {
    btn.addEventListener('click', () => {
        const modal = document.getElementById('modal-patrimonio');
        const form = document.getElementById('form-edit-patrimonio');
        form.action = btn.dataset.action;
        const period = document.getElementById('modal-patrimonio-period');
        if (period) period.textContent = btn.dataset.period || '';
        form.querySelectorAll('input[name]').forEach(input => {
            if (btn.dataset[input.name] !== undefined) input.value = btn.dataset[input.name];
        });
        openModal(modal);
    });
});

// Close on the X / "Annulla" buttons, on backdrop click, and on Escape.
document.querySelectorAll('[data-close-modal]').forEach(el => {
    el.addEventListener('click', () => closeModal(el.closest('.modal-overlay')));
});
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeModal(overlay);
    });
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.open').forEach(closeModal);
});

// ---- CONFIRM DELETE ----
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
        if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
});

// ---- SIDEBAR TOGGLE (MOBILE) ----
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const sidebar = document.querySelector('.sidebar');

if (sidebarToggle && sidebar && sidebarOverlay) {
    const openSidebar = () => {
        sidebar.classList.add('open');
        sidebarOverlay.classList.add('open');
    };
    const closeSidebar = () => {
        sidebar.classList.remove('open');
        sidebarOverlay.classList.remove('open');
    };

    sidebarToggle.addEventListener('click', () => {
        sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
    });
    sidebarOverlay.addEventListener('click', closeSidebar);

    sidebar.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', closeSidebar);
    });
}
