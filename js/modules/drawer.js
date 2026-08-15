// Drawer del historial de sesiones (antes era una sidebar siempre visible).
// Mismo patrón que el reader-overlay: clase .active togglea la visibilidad,
// con backdrop clickeable y cierre con Esc.

function setDrawerOpen(open) {
    const drawer = document.getElementById('historyDrawer');
    const backdrop = document.getElementById('drawerBackdrop');
    const trigger = document.getElementById('historyTrigger');
    if (!drawer || !backdrop) return;
    drawer.classList.toggle('active', open);
    backdrop.classList.toggle('active', open);
    if (trigger) {
        trigger.setAttribute('aria-expanded', String(open));
        // El drawer se dibuja arriba del botón trigger (mismo rincón de la
        // pantalla) - lo tapa mientras está abierto, así que lo ocultamos
        // para que no quede un botón fantasma sin poder clickearse.
        trigger.classList.toggle('drawer-open', open);
    }
}

export function closeHistoryDrawer() {
    setDrawerOpen(false);
}

export function initHistoryDrawer() {
    const trigger = document.getElementById('historyTrigger');
    const backdrop = document.getElementById('drawerBackdrop');
    const closeBtn = document.getElementById('drawerClose');
    const drawer = document.getElementById('historyDrawer');
    if (!trigger || !drawer) return;

    trigger.addEventListener('click', () => {
        setDrawerOpen(!drawer.classList.contains('active'));
    });
    backdrop.addEventListener('click', () => setDrawerOpen(false));
    closeBtn.addEventListener('click', () => setDrawerOpen(false));

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && drawer.classList.contains('active')) {
            setDrawerOpen(false);
        }
    });

    // Elegir una sesión del historial cierra el drawer solo, para no tener
    // que cerrarlo a mano después de elegir.
    drawer.querySelector('.session-list').addEventListener('click', (e) => {
        if (e.target.closest('.session-item')) setDrawerOpen(false);
    });
}
