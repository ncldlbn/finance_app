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

// ---- TOAST ----
// Notifiche in basso a destra (a tutta larghezza su telefono). Conferme e avvisi spariscono da soli
// (con pausa al passaggio del mouse o del fuoco); gli errori restano finché non li si chiude.
// Il contenitore è una regione "live": i lettori di schermo annunciano i messaggi quando compaiono.
// Esc chiude l'ultima notifica; un errore mostrato al caricamento della pagina prende il fuoco.
const TOAST_ICON = { success: 'check_circle', info: 'info', warning: 'warning_amber', error: 'error_outline' };
const TOAST_MS = { success: 4000, info: 5000, warning: 7000 };

function toastContainer() {
    let c = document.getElementById('toast-container');
    if (!c) {
        c = document.createElement('div');
        c.id = 'toast-container';
        c.setAttribute('role', 'region');
        c.setAttribute('aria-label', 'Notifiche');
        c.setAttribute('aria-live', 'polite');
        document.body.appendChild(c);
    }
    return c;
}

function dismissToast(toast) {
    if (!toast || toast.dataset.closing) return;
    toast.dataset.closing = '1';
    clearTimeout(toast._timer);
    // Il fuoco torna alla pagina, non resta su un elemento che sparisce.
    if (toast.contains(document.activeElement) && toast._returnFocus && document.contains(toast._returnFocus)) toast._returnFocus.focus();
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 250);
}

function showToast(msg, type = 'success', opts = {}) {
    if (!TOAST_ICON[type]) type = 'info';
    const container = toastContainer();
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    // Gli errori sono "assertivi" (annunciati subito); il resto è cortese.
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.tabIndex = -1;
    const icon = document.createElement('span');
    icon.className = 'material-icons-round';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = TOAST_ICON[type];
    const text = document.createElement('span');
    text.className = 'toast-text';
    text.textContent = msg;                       // textContent: nessun HTML dal messaggio
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Chiudi notifica');
    close.innerHTML = '<span class="material-icons-round" aria-hidden="true">close</span>';
    close.addEventListener('click', () => dismissToast(toast));
    toast.append(icon, text, close);
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));

    const ms = TOAST_MS[type];
    if (ms) {                                     // conferme e avvisi: sparizione automatica, con pausa
        const arm = () => { clearTimeout(toast._timer); toast._timer = setTimeout(() => dismissToast(toast), ms); };
        toast.addEventListener('mouseenter', () => clearTimeout(toast._timer));
        toast.addEventListener('mouseleave', arm);
        toast.addEventListener('focusin', () => clearTimeout(toast._timer));
        toast.addEventListener('focusout', arm);
        arm();
    }
    if (type === 'error' && opts.focus) {
        toast._returnFocus = document.activeElement;
        toast.focus({ preventScroll: true });
    }
    return toast;
}

// Esc chiude l'ultima notifica (ma non se sta chiudendo un modale: quello ha la precedenza).
document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || document.querySelector('.modal-overlay.open')) return;
    const all = document.querySelectorAll('#toast-container .toast:not([data-closing])');
    if (all.length) dismissToast(all[all.length - 1]);
});

// Campo non valido: bordo rosso finché non lo si modifica.
function markInvalid(field) {
    if (!field) return;
    field.classList.add('is-invalid');
    field.setAttribute('aria-invalid', 'true');
    const clear = () => { field.classList.remove('is-invalid'); field.removeAttribute('aria-invalid'); };
    field.addEventListener('input', clear, { once: true });
    field.addEventListener('change', clear, { once: true });
}
// Validazione del browser (campo obbligatorio, formato…): lo evidenzia e lo dice con un toast.
let invalidFocused = false;
document.addEventListener('invalid', e => {
    const f = e.target; if (!f.classList) return;
    e.preventDefault();                           // niente fumetto del browser: c'è già il toast
    markInvalid(f);
    if (!invalidFocused) { invalidFocused = true; f.focus(); setTimeout(() => { invalidFocused = false; }, 0); }
    const label = f.closest('.form-group')?.querySelector('label')?.textContent?.trim();
    if (!document.querySelector('#toast-container .toast-error[data-validation]')) {
        const t = showToast(label ? `Controlla il campo «${label}»: ${f.validationMessage}` : f.validationMessage, 'error');
        t.dataset.validation = '1';
    }
}, true);

// Messaggi dal server (flash): arrivano come JSON nella pagina e diventano notifiche.
// "error:euro" = errore che riguarda il campo di nome "euro" (viene evidenziato e messo a fuoco).
document.addEventListener('DOMContentLoaded', () => {
    const el = document.getElementById('flash-data');
    if (!el) return;
    let items = [];
    try { items = JSON.parse(el.textContent); } catch (err) { return; }
    let focused = false;
    items.forEach(([cat, msg]) => {
        const [type, field] = String(cat).split(':');
        const t = showToast(msg, type);
        if (type === 'error' && field) {
            const input = document.querySelector(`.tab-panel.active [name="${field}"], form [name="${field}"]`);
            markInvalid(input);
            if (input && !focused) { input.focus(); focused = true; }
        }
        if (type === 'error' && !focused) { t._returnFocus = document.activeElement; t.focus({ preventScroll: true }); focused = true; }
    });
});

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
