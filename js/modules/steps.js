// Controlador del flujo en 3 pasos: 1) Ingreso, 2) Selección/generador de
// prompt, 3) Exportador. Antes todo vivía junto en una sola pantalla; ahora
// cada paso es una sección que se muestra/oculta, con un indicador arriba
// que también sirve para volver a un paso ya visitado.
import { state } from '../state.js';
import { parseClipsFromTimeline } from './clips.js';

const TOTAL_STEPS = 3;

export function goToStep(n) {
    n = Math.min(Math.max(1, n), TOTAL_STEPS);
    state.currentStep = n;
    state.maxReachedStep = Math.max(state.maxReachedStep, n);

    document.querySelectorAll('.step-panel').forEach((el) => {
        el.classList.toggle('active', Number(el.dataset.step) === n);
    });

    updateStepperUI();

    // Al entrar al paso 3 (exportador), dejamos listo el panel de clips
    // (antes esto pasaba al togglear el panel a mano; ahora lo dispara
    // directamente entrar al paso).
    if (n === 3) {
        const clipExporter = document.getElementById('clipExporter');
        if (clipExporter) clipExporter.classList.add('active');
        if (state.originalTimeline && state.clipsList.length === 0) {
            parseClipsFromTimeline();
        }
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateStepperUI() {
    document.querySelectorAll('.stepper .step').forEach((btn) => {
        const s = Number(btn.dataset.step);
        const reachable = s <= state.maxReachedStep;
        btn.classList.toggle('active', s === state.currentStep);
        btn.classList.toggle('done', s < state.currentStep);
        btn.classList.toggle('reachable', reachable);
        btn.disabled = !reachable;
        btn.setAttribute('aria-current', s === state.currentStep ? 'step' : 'false');
    });
}

/**
 * Habilita el botón "Siguiente" del paso 1 sin navegar todavía (el usuario
 * decide cuándo avanzar) y desbloquea el stepper hasta el final: una vez
 * que hay un análisis, los 3 pasos tienen sentido y se puede saltar entre
 * ellos con el indicador de arriba, no solo con "Siguiente".
 */
export function revealStep1Next() {
    const btn = document.getElementById('btnStep1Next');
    if (btn) btn.hidden = false;
    state.maxReachedStep = TOTAL_STEPS;
    updateStepperUI();
}

/** Desbloquea todo el stepper y va directo al paso 2 (usado al cargar una sesión del historial: ya está analizada, no hace falta pasar por el botón "Siguiente"). */
export function openAnalyzedSession() {
    state.maxReachedStep = TOTAL_STEPS;
    goToStep(2);
}

/** Vuelve todo al estado inicial (usado por "Nueva sesión"). */
export function resetSteps() {
    const btn = document.getElementById('btnStep1Next');
    if (btn) btn.hidden = true;
    state.maxReachedStep = 1;
    goToStep(1);
}

export function initStepper() {
    document.querySelectorAll('.stepper .step').forEach((btn) => {
        btn.addEventListener('click', () => {
            const target = Number(btn.dataset.step);
            if (target <= state.maxReachedStep) goToStep(target);
        });
    });
    document.querySelectorAll('[data-goto]').forEach((btn) => {
        btn.addEventListener('click', () => goToStep(Number(btn.dataset.goto)));
    });
    const next1 = document.getElementById('btnStep1Next');
    if (next1) next1.addEventListener('click', () => goToStep(2));
    const next2 = document.getElementById('btnStep2Next');
    if (next2) next2.addEventListener('click', () => goToStep(3));

    updateStepperUI();
}
