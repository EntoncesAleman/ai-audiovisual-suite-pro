// Pantalla de login. La escena cósmica de fondo es puro CSS (sin JS);
// acá va la interacción del formulario y la verificación real contra el
// backend (ver main.py: require_api_key / GET /auth/check).
//
// No hay usuarios/roles todavía - "iniciar sesión" hoy significa "conocer
// el API_ACCESS_KEY compartido que configuró quien deployó el servidor".
// El campo de email no se valida contra nada real (no hay backend de
// usuarios); se pide igual para no romper el diseño de la pantalla, pero
// lo único que realmente se verifica es la contraseña como API key.
import { setApiKey, clearApiKey } from './utils/storage.js';

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

function showGateError(message) {
    const errorEl = document.getElementById('gateError');
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.hidden = !message;
}

function setupForm() {
    const form = document.getElementById('loginForm');
    const submitBtn = document.getElementById('submitBtn');
    const email = document.getElementById('email');
    const password = document.getElementById('password');
    if (!form || !submitBtn) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        showGateError('');

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

        submitBtn.classList.add('is-loading');
        submitBtn.disabled = true;

        try {
            const res = await fetch(`${window.location.origin}/auth/check`, {
                headers: { 'X-API-Key': password.value }
            });
            if (res.ok) {
                // auth_enabled=false significa que el servidor no tiene
                // API_ACCESS_KEY configurada: no hay nada que validar
                // todavía, cualquier clave "pasa". Igual guardamos lo que
                // se ingresó para que, el día que se active, ya quede listo.
                setApiKey(password.value);
                window.location.href = '/';
                return;
            }
            if (res.status === 401) {
                clearApiKey();
                document.getElementById('password').closest('.field').classList.add('is-error');
                showGateError('Contraseña incorrecta.');
            } else {
                showGateError(`El servidor respondió con un error (HTTP ${res.status}). Probá de nuevo en un momento.`);
            }
        } catch (err) {
            showGateError('No se pudo contactar al servidor. Revisá tu conexión e intentá de nuevo.');
        } finally {
            submitBtn.classList.remove('is-loading');
            submitBtn.disabled = false;
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupPasswordToggle();
    setupForm();
});
