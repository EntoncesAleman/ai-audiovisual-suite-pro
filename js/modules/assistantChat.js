import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';
import { authHeaders } from '../utils/storage.js';
import { escapeHtml } from '../utils/dom.js';
import { parseAiTimestampsText, tsToSeconds, estimateDurationSeconds } from '../utils/helpers.js';

function proposedCuts(content) {
    const duration = estimateDurationSeconds(state.originalTimeline);
    return parseAiTimestampsText(content || '').filter(clip => tsToSeconds(clip.end) > tsToSeconds(clip.start) && tsToSeconds(clip.start) >= 0 && (!duration || tsToSeconds(clip.end) <= duration));
}

/**
 * Chat de ida y vuelta del modo "Assistant" (ver /assistant-chat en main.py):
 * a diferencia del campo "Prompt Libre" (una instrucción final para armar
 * clips), esto es una conversación real sobre el material ya transcripto -
 * preguntas, ideas, pedir que aclare algo - antes de decidir qué pedirle
 * en la instrucción final de arriba.
 */
let sending = false;

export function renderAssistantChat() {
    document.dispatchEvent(new CustomEvent('editor-changed'));
    const list = document.getElementById('assistantChatMessages');
    if (!list) return;
    if (state.assistantChatHistory.length === 0) {
        list.innerHTML = '<div class="assistant-chat-empty">Preguntale algo sobre el material (ej: "¿de qué temas habla?", "dame 3 ideas de clips fuertes")...</div>';
    } else {
        list.innerHTML = state.assistantChatHistory.map((m,index) => {
            const role = m.role === 'user' ? 'user' : 'assistant';
            const cuts = role === 'assistant' ? proposedCuts(m.content) : [];
            return `<div class="assistant-chat-msg assistant-chat-msg-${role}">${escapeHtml(m.content)}
                ${cuts.length ? `<details><summary>Revisar ${cuts.length} cortes propuestos</summary>${cuts.map(clip => `<p>${escapeHtml(clip.start)} → ${escapeHtml(clip.end)} · ${escapeHtml(clip.label)}</p>`).join('')}<button class="studio-nav-btn" data-chat-cuts="${index}">Agregar estos cortes al editor</button></details>` : ''}</div>`;
        }).join('');
    }
    if (!list.dataset.actionsBound) {
        list.dataset.actionsBound = '1';
        list.addEventListener('click', event => {
            const button = event.target.closest('[data-chat-cuts]'); if (!button) return;
            const message = state.assistantChatHistory[Number(button.dataset.chatCuts)];
            const cuts = proposedCuts(message?.content);
            for (const cut of cuts) {
                if (!state.clipsList.some(existing => existing.start === cut.start && existing.end === cut.end)) state.clipsList.push({ ...cut, id:crypto.randomUUID(), selected:true });
            }
            document.dispatchEvent(new CustomEvent('editor-restored'));
            button.textContent = 'Cortes agregados'; button.disabled = true;
        });
    }
    list.scrollTop = list.scrollHeight;
}

export function clearAssistantChat() {
    state.assistantChatHistory = [];
    renderAssistantChat();
}

export async function sendAssistantChatMessage() {
    if (sending) return;
    const input = document.getElementById('assistantChatInput');
    const text = (input.value || '').trim();
    if (!text) return;
    if (!state.originalTimeline) {
        alert("Primero procesá un video - todavía no hay transcripción para conversar sobre eso.");
        return;
    }

    state.assistantChatHistory.push({ role: 'user', content: text });
    input.value = '';
    renderAssistantChat();

    sending = true;
    const list = document.getElementById('assistantChatMessages');
    list.insertAdjacentHTML('beforeend', '<div class="assistant-chat-msg assistant-chat-msg-assistant assistant-chat-typing" id="assistantChatTyping">Pensando…</div>');
    list.scrollTop = list.scrollHeight;

    try {
        const res = await fetch(`${BACKEND_URL}/assistant-chat`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ transcript: state.originalTimeline, messages: state.assistantChatHistory }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error del asistente.');
        state.assistantChatHistory.push({ role: 'assistant', content: data.reply });
    } catch (e) {
        state.assistantChatHistory.push({ role: 'assistant', content: `⚠ ${e.message}` });
    } finally {
        sending = false;
        document.getElementById('assistantChatTyping')?.remove();
        renderAssistantChat();
    }
}

export function handleAssistantChatKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendAssistantChatMessage();
    }
}

window.sendAssistantChatMessage = sendAssistantChatMessage;
window.handleAssistantChatKeydown = handleAssistantChatKeydown;
window.clearAssistantChat = clearAssistantChat;
