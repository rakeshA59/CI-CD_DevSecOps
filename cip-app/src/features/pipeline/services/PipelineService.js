import apiRepository, { API_BASE } from '@/core/repositories/apiRepository';

export const startPipeline = (source, branch, llmProvider, options, mode = 'quick') =>
    apiRepository.post('/pipelines/start', {
        source,
        branch: branch || null,
        llm_provider: llmProvider,
        options,
        mode,
    });

/** Guided flow: resume a paused run with the questionnaire answers / the approval decision. */
export const submitAnswers = (taskId, answers) =>
    apiRepository.post(`/pipelines/${encodeURIComponent(taskId)}/answers`, { answers });
export const submitApproval = (taskId, decision, by, comment) =>
    apiRepository.post(`/pipelines/${encodeURIComponent(taskId)}/approval`, {
        decision,
        by,
        comment,
    });
export const stopPipeline = (taskId) =>
    apiRepository.post(`/pipelines/${encodeURIComponent(taskId)}/stop`, {});
export const testResultsUrl = (taskId, name) =>
    `${API_BASE}/pipelines/${encodeURIComponent(taskId)}/test-results/${name}`;
export const screenshotUrl = (taskId, name) =>
    `${API_BASE}/pipelines/${encodeURIComponent(taskId)}/screenshots/${name}`;
export const stepReportUrl = (taskId, stepId) =>
    `${API_BASE}/pipelines/${encodeURIComponent(taskId)}/steps/${encodeURIComponent(stepId)}/report.html`;
export const getStepDocs = () => apiRepository.get('/pipelines/step-docs');
export const getDashboard = () => apiRepository.get('/pipelines/dashboard');

export const getPipeline = (taskId) =>
    apiRepository.get(`/pipelines/${encodeURIComponent(taskId)}`);

export const pdfUrl = (taskId) => `${API_BASE}/pipelines/${encodeURIComponent(taskId)}/report.pdf`;

/**
 * Live agent events of a run (server-sent events). Returns a function that closes the stream.
 * The server also ends the stream when a guided run pauses (questionnaire / approval) – that arrives as onerror → onEnd.
 */
export const streamPipelineEvents = (taskId, onEvent, onEnd, after = 0) => {
    const source = new EventSource(
        `${API_BASE}/pipelines/${encodeURIComponent(taskId)}/stream?after=${after}`
    );
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
