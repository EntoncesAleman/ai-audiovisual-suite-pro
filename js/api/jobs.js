import { studioRequest } from '../modules/workspaceSync.js';
import { writeAccountValue } from '../utils/storage.js';

export async function submitStudioJob(action, payload, signal) {
    const requestId = crypto.randomUUID();
    writeAccountValue('last_job_request', requestId);
    const job = await studioRequest('/studio/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, payload, request_id: requestId }), signal });
    document.dispatchEvent(new CustomEvent('jobs-changed', { detail: job }));
    return job;
}

export async function waitForStudioJob(id, onUpdate = () => {}, signal) {
    while (true) {
        const job = await studioRequest(`/studio/jobs/${encodeURIComponent(id)}`, { signal });
        onUpdate(job);
        if (job.status === 'done') return job;
        if (job.status === 'error' || job.status === 'interrupted') throw new Error(job.message || 'El trabajo no pudo terminar.');
        await new Promise((resolve, reject) => {
            if (signal?.aborted) { reject(signal.reason); return; }
            const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, 1500);
            function abort() { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(signal.reason); }
            signal?.addEventListener('abort', abort, { once: true });
        });
    }
}

// A Response with SSE events preserves existing export UI while the real work is detached.
export async function durableJobFetch(url, options = {}) {
    const actionMap = { '/analyze-url-stream': 'analyze-url', '/analyze-video-stream': 'analyze-file',
        '/export-clips': 'export-clips', '/export-reel': 'export-reel', '/export-carousel': 'export-carousel',
        '/export-premiere-xml': 'export-premiere', '/export-capcut': 'export-capcut-local' };
    const action = actionMap[new URL(url, window.location.origin).pathname];
    if (!action) return fetch(url, options);
    let payload;
    if (options.body instanceof FormData) {
        const upload = new FormData();
        upload.append('file', options.body.get('file'));
        const media = await studioRequest('/studio/media', { method: 'POST', body: upload, signal: options.signal || AbortSignal.timeout(15 * 60 * 1000) });
        payload = { asset_id: media.id, engine: options.body.get('engine') || 'auto' };
    } else payload = JSON.parse(options.body || '{}');
    const job = await submitStudioJob(action, payload, options.signal);
    const encoder = new TextEncoder();
    let closed = false;
    let lastSeq = 0;
    const stream = new ReadableStream({
        start(controller) {
            const emit = event => { if (!closed) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); };
            emit({ stage: 'queued', message: 'Trabajo guardado. Podés consultar el resultado en Trabajos aunque cierres esta pestaña.' });
            waitForStudioJob(job.id, update => {
                for (const event of update.events || []) {
                    if ((event.seq || 0) > lastSeq) { emit(event); lastSeq = event.seq; }
                }
                if (!closed) controller.enqueue(encoder.encode(': keep-alive\n\n'));
            }, options.signal).then(() => {
                if (!closed) { closed = true; controller.close(); }
                document.dispatchEvent(new CustomEvent('jobs-changed'));
            }).catch(error => {
                if (closed) return;
                if (options.signal?.aborted) { closed = true; controller.error(error); }
                else { emit({ stage: 'error', message: error.message }); closed = true; controller.close(); }
            });
        },
        cancel() { closed = true; },
    });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
}
