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

// ---- INLINE AUTO-SAVE ----
// Forms marked .js-autosave save automatically as soon as a field changes
// (the "change" event fires when the user finishes editing a field) and show
// a toast instead of reloading the page. The Save button stays as a fallback.
document.querySelectorAll('form.js-autosave').forEach(form => {
    const save = () => {
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(r => {
                if (!r.ok) throw new Error('save failed');
                showToast('Modifica salvata');
            })
            .catch(() => showToast('Errore nel salvataggio', 'error'));
    };
    form.addEventListener('change', save);
    form.addEventListener('submit', e => { e.preventDefault(); save(); });
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
