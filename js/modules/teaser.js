import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';
import { generateIAPrompt } from './prompts.js';

export async function loadTeaserTemplates() {
    try {
        const res = await fetch(`${BACKEND_URL}/teaser-templates`);
        if (res.ok) {
            state.TEASER_TEMPLATES = await res.json();
        } else {
            throw new Error("backend sin /teaser-templates");
        }
    } catch (e) {
        console.warn("No se pudieron cargar las plantillas de teaser:", e);
        // Fallback mínimo
        state.TEASER_TEMPLATES = {
            plantillas: {
                generico: {
                    nombre: "🎬 Genérico",
                    enmarque_inicial: "Identificá el tema central del episodio.",
                    gancho: "Buscá los testimonios más impactantes.",
                    nudo: "Mostrá la frustración o complejidad del tema.",
                    revelacion: "Rescatá las declaraciones del experto.",
                    cierre: "Remate emocional del anfitrión."
                }
            }
        };
    }
    populateTeaserTemplateSelect();
}

export function populateTeaserTemplateSelect() {
    const sel = document.getElementById("teaserTemplate");
    sel.innerHTML = "";
    const plantillas = state.TEASER_TEMPLATES.plantillas || {};
    for (const [key, val] of Object.entries(plantillas)) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = val.nombre;
        sel.appendChild(opt);
    }
    // Aplicar la primera plantilla por defecto (suele ser "genérico")
    if (sel.options.length > 0) {
        applyTeaserTemplate();
    }
}

export function applyTeaserTemplate() {
    const key = document.getElementById("teaserTemplate").value;
    const plantilla = state.TEASER_TEMPLATES?.plantillas?.[key];
    if (!plantilla) return;
    document.getElementById("teaserEnmarque").value = plantilla.enmarque_inicial || "";
    document.getElementById("teaserGancho").value = plantilla.gancho || "";
    document.getElementById("teaserNudo").value = plantilla.nudo || "";
    document.getElementById("teaserRevelacion").value = plantilla.revelacion || "";
    document.getElementById("teaserCierre").value = plantilla.cierre || "";
    generateIAPrompt();
}

export function resetTeaserToTemplate() {
    if (confirm("¿Volver a los valores de la plantilla? Vas a perder los cambios manuales.")) {
        applyTeaserTemplate();
    }
}

export function clearTeaserFields() {
    if (!confirm("¿Vaciar todos los campos? El prompt va a quedar en 'modo libre', dejando que la IA defina cada acto del teaser según el material. Esto suele dar variaciones distintas en cada tirada.")) return;
    document.getElementById("teaserEnmarque").value = "";
    document.getElementById("teaserGancho").value = "";
    document.getElementById("teaserNudo").value = "";
    document.getElementById("teaserRevelacion").value = "";
    document.getElementById("teaserCierre").value = "";
    generateIAPrompt();
}

/**
 * Regenera el prompt del teaser y da feedback visual claro:
 * el botón parpadea verde, el cuadro del prompt hace un flash y
 * la vista hace scroll automático hacia el prompt actualizado.
 * Si no hay sesión cargada, avisa al usuario.
 *
 * NOTA: los campos pueden estar en blanco. En ese caso, el prompt
 * se arma indicándole a la IA que defina libremente ese acto según
 * el material. Eso permite obtener variaciones distintas en cada
 * tirada con el mismo episodio.
 */
export function regenerateTeaserPrompt() {
    if (!state.currentData) {
        alert("Primero cargá o procesá una sesión de video para regenerar el prompt.");
        return;
    }

    // Regenerar el prompt (los campos vacíos quedan como instrucción libre para la IA)
    generateIAPrompt();

    // Feedback visual: botón verde momentáneo
    const btn = document.getElementById("btnRegenerateTeaser");
    const originalText = btn.textContent;
    btn.classList.add("flash");
    btn.textContent = "✓ Prompt actualizado";

    setTimeout(() => {
        btn.classList.remove("flash");
        btn.textContent = originalText;
    }, 1200);

    // Flash en el cuadro del prompt
    const promptBox = document.getElementById("promptOutput");
    promptBox.classList.remove("flash"); // reset por si ya estaba
    // Forzar reflow para que la animación se reinicie
    void promptBox.offsetWidth;
    promptBox.classList.add("flash");
    setTimeout(() => promptBox.classList.remove("flash"), 800);

    // Scroll suave hacia el cuadro del prompt
    promptBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
