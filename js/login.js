// Pantalla de login: por ahora es solo interfaz, sin autenticación real todavía.
// La escena cósmica de fondo es puro CSS (sin JS); acá solo va la interacción del formulario.

function setupPasswordToggle() {
    const btn = document.getElementById('togglePassword');
    const input = document.getElementById('password');
    if (!btn || !input) return;

    btn.addEventListener('click', () => {
        const showing = input.type === 'text';
        input.type = showing ? 'password' : 'text';
        btn.setAttribute('aria-pressed', String(!showing));
        btn.setAttribute('aria-label', showing ? 'Mostrar contraseña' : 'Ocultar contraseña');
    });
}

function setupForm() {
    const form = document.getElementById('loginForm');
    const submitBtn = document.getElementById('submitBtn');
    const email = document.getElementById('email');
    const password = document.getElementById('password');
    if (!form || !submitBtn) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();

        const fields = [email, password];
        let hasError = false;
        fields.forEach((input) => {
            const field = input.closest('.field');
            field.classList.remove('is-error');
            if (!input.value.trim()) {
                hasError = true;
                field.classList.add('is-error');
            }
        });
        if (hasError) return;

        // Todavía no hay backend de autenticación conectado: esto es solo
        // la micro-interacción visual del botón (sin envío real).
        submitBtn.classList.add('is-loading');
        submitBtn.disabled = true;
        setTimeout(() => {
            submitBtn.classList.remove('is-loading');
            submitBtn.disabled = false;
        }, 1100);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupPasswordToggle();
    setupForm();
});
