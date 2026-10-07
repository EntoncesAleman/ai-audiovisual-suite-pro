import { BACKEND_URL } from '../config.js';
import { getCurrentUser } from './auth.js';
import { fetchWithTimeout } from '../utils/helpers.js';

const features = [
    ['studio', 'Studio con barra lateral', 'Todas las herramientas en un mismo espacio, con reproductor y actividad siempre visibles.', 'amber'],
    ['render', 'Montaje y audio', 'Encuadre manual, seguimiento del hablante, música, mezcla y volumen de la voz.', 'blue'],
    ['voice', 'Voz con IA', 'Convertí tus textos en audio para narraciones y voces adicionales.', 'violet'],
    ['images', 'Imágenes y miniaturas', 'Creá recursos desde una descripción o una imagen de referencia.', 'rose'],
    ['premiere', 'Proyectos para Premiere', 'Llevá los clips a una secuencia editable y continuá trabajando en Premiere.', 'violet'],
    ['capcut', 'Paquetes para CapCut', 'Descargá clips y subtítulos para importarlos como proyecto editable. Compatibilidad beta.', 'blue'],
    ['campaign', 'Campañas para tus clips', 'Prepará títulos, textos, hashtags y propuestas de imágenes para tus publicaciones.', 'amber'],
    ['brand', 'Tu identidad de marca', 'Guardá colores, logo y estilo para aplicarlos a imágenes y campañas.', 'rose'],
];

function featureIcon(id, icon) {
    if (id !== 'studio') return icon(id);
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M8 3v18M8 9h14M4 7h1m-1 4h1m-1 4h1M11 13h8m-8 4h5"/></svg>';
}

export function initFreeOffer(icon) {
    if (document.getElementById('freeProShowcase') || !document.querySelector('.dashboard')) return;
    const section = document.createElement('section');
    section.id = 'freeProShowcase'; section.className = 'pro-showcase'; section.hidden = true;
    section.setAttribute('aria-labelledby', 'freeProTitle');
    section.innerHTML = `<header><div><span class="pro-showcase-eyebrow">Cuando quieras ir más allá</span><h2 id="freeProTitle">Todo lo que podés hacer con PRO</h2><p>Estas herramientas se suman al editor gratuito cuando tenés un plan PRO.</p></div><button class="studio-primary" type="button" id="requestProAccess">Solicitar PRO</button></header>
      <div class="pro-feature-grid">${features.map(([id, title, description, color]) => `<article class="pro-feature-card"><div class="pro-feature-art" data-color="${color}" aria-hidden="true"><span class="pro-feature-label">PRO</span><span class="pro-feature-orbit"></span>${featureIcon(id, icon)}<span class="pro-feature-lines"><i></i><i></i><i></i></span></div><h3>${title}</h3><p>${description}</p></article>`).join('')}</div>
      <p class="pro-provider-note">Por ahora PRO también usa modelos gratuitos. La IA está sujeta a cuotas y disponibilidad; las imágenes pueden no tener cuota gratuita. Las APIs de modelos pagos se incorporarán más adelante.</p>`;
    document.querySelector('.below-hero').after(section);
    document.getElementById('requestProAccess').addEventListener('click', requestPro);
}

function requestPro() {
    let dialog = document.getElementById('proRequestDialog');
    if (!dialog) {
        dialog = document.createElement('dialog'); dialog.id = 'proRequestDialog'; dialog.className = 'account-settings';
        dialog.innerHTML = `<form method="dialog"><header><h2>Solicitar acceso PRO</h2><button aria-label="Cerrar solicitud PRO">✕</button></header></form><p>Dejá tu solicitud. El administrador te indicará cómo acceder al plan PRO.</p><form id="proRequestForm"><label>Tu nombre o usuario<input id="proRequestName" required maxlength="100" autocomplete="name"></label><label>Cómo contactarte<input id="proRequestContact" required maxlength="200" placeholder="Email u otro medio de contacto"></label><button type="submit" class="studio-primary">Enviar solicitud</button></form><p id="proRequestStatus" role="status"></p>`;
        document.body.append(dialog);
        document.getElementById('proRequestForm').addEventListener('submit', async event => {
            event.preventDefault(); const button = event.target.querySelector('[type="submit"]'); button.disabled = true;
            const status = document.getElementById('proRequestStatus'); status.textContent = 'Enviando…';
            try {
                const user = getCurrentUser();
                const response = await fetchWithTimeout(`${BACKEND_URL}/access-requests`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
                    name: document.getElementById('proRequestName').value.trim(), project:'Plan PRO · AV Suite',
                    reason:`Solicito acceso al plan PRO. Contacto: ${document.getElementById('proRequestContact').value.trim()}.${user?.role !== 'GUEST' ? ` Cuenta actual: ${user?.username || ''}.` : ''}`,
                })});
                const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'No se pudo enviar la solicitud.');
                status.textContent = 'Solicitud enviada. El administrador te contactará para continuar.';
                event.target.hidden = true;
            } catch (error) { status.textContent = error.message || 'No se pudo enviar la solicitud. Probá nuevamente.'; }
            finally { button.disabled = false; }
        });
    }
    const user = getCurrentUser();
    document.getElementById('proRequestName').value = user?.role === 'GUEST' ? '' : user?.username || '';
    document.getElementById('proRequestForm').hidden = false; document.getElementById('proRequestStatus').textContent = '';
    dialog.showModal();
}
