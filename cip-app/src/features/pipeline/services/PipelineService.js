import apiRepository, { API_BASE } from '@/core/repositories/apiRepository';

export const startPipeline = (source, branch, llmProvider, options) =>
    apiRepository.post('/pipelines/start', { source, branch: branch || null, llm_provider: llmProvider, options });

export const getPipeline = (taskId) => apiRepository.get(`/pipelines/${encodeURIComponent(taskId)}`);

export const pdfUrl = (taskId) => `${API_BASE}/pipelines/${encodeURIComponent(taskId)}/report.pdf`;

/**
 * Live agent events of a run (server-sent events). Returns a function that closes the stream.
 */
export const streamPipelineEvents = (taskId, onEvent, onEnd) => {
    const source = new EventSource(`${API_BASE}/pipelines/${encodeURIComponent(taskId)}/stream`);
    source.onmessage = (msg) => {
        const event = JSON.parse(msg.data);
        onEvent(event);
        if (event.status === 'SYSTEM_END') {
            source.close();
            onEnd?.(event);
        }
    };
    source.onerror = () => {
        source.close();
        onEnd?.(null);
    };
    return () => source.close();
};

export const getScanners = () => apiRepository.get('/pipelines/scanners');
