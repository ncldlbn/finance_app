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

// ---- CONFIRM DELETE ----
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
        if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
});
