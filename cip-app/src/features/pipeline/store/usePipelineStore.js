import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import {
    getPipeline,
    stopPipeline,
    streamPipelineEvents,
    submitAnswers,
    submitApproval,
} from '../services/PipelineService';

/**
 * Pipeline Store – live state of one run.
 *
 *  - events:      every agent event from the SSE stream (shown in the live log)
 *  - nodeStatus:  agent node → running / passed / failed … (derived from events while the run is live)
 *  - components:  planned by the planner agent (lanes of the pipeline view)
 *  - run:         the full run record from MongoDB (steps, gates, report) once the run has finished
 */

// Agent node (event) → step record id
export const nodeToStep = (node) =>
    ({
        checkout_agent: 'checkout',
        planner_agent: 'plan',
        questionnaire_agent: 'questionnaire',
        pipeline_designer: 'design',
        release_agent: 'release',
        deploy_agent: 'deploy',
        functional_test_agent: 'functional',
        ui_test_agent: 'ui_tests',
        publish_tests_agent: 'publish_tests',
        approval_gate: 'approval',
        uat_deploy_agent: 'deploy_uat',
        report_agent: 'report',
    })[node] || node;

const STATUS = {
    START: 'running',
    PROGRESS: 'running',
    COMMAND: 'running',
    END: 'passed',
    ERROR: 'failed',
    SKIPPED: 'skipped',
};

const initialState = {
    taskId: null,
    run: null,
    events: [],
    nodeStatus: {},
    components: [],
    executionPlan: [],
    scanners: [], // [{name, label}] announced by the security agent
    spec: [], // guided flow: the derived pipeline (stages, tools, MCP, why)
    live: false,
    selectedStep: null,
    lastEventId: 0,
};

let closeStream = null;

const usePipelineStore = create(
    devtools((set, get) => ({
        ...initialState,

        reset: () => {
            closeStream?.();
            set({ ...initialState });
        },

        selectStep: (stepId) => set({ selectedStep: stepId }),

        loadRun: async (taskId) => {
            const run = await getPipeline(taskId);
            set({
                run,
                components: run.components || get().components,
                executionPlan: run.execution_plan || get().executionPlan,
                spec: run.spec || get().spec,
            });
            return run;
        },

        open: async (taskId) => {
            closeStream?.();
            set({ ...initialState, taskId, live: true });
            const run = await get().loadRun(taskId);
            if (get().taskId !== taskId) return; // another run was opened meanwhile
            get().follow(taskId, 0);
            if (!run.active && run.status !== 'RUNNING') set({ live: false });
        },

        /** Stream the run's events from `after` on; when the stream ends (finished or paused) reload the run. */
        follow: (taskId, after) => {
            closeStream?.();
            closeStream = streamPipelineEvents(
                taskId,
                (event) => get().addEvent(event),
                async () => {
                    set({ live: false });
                    await get().loadRun(taskId);
                },
                after
            );
        },

        /** Guided flow: send the questionnaire answers / approval decision and keep following the run. */
        resume: async (kind, payload) => {
            const { taskId, lastEventId } = get();
            if (kind === 'answers') await submitAnswers(taskId, payload);
            else await submitApproval(taskId, payload.decision, payload.by, payload.comment);
            set((s) => ({ live: true, run: { ...s.run, status: 'RUNNING', pending: null } }));
            get().follow(taskId, lastEventId);
        },

        /** Stop button: a running run ends its stream (→ reload); a paused one is reloaded here. */
        stop: async () => {
            const { taskId, live } = get();
            await stopPipeline(taskId);
            if (!live) await get().loadRun(taskId);
        },

        addEvent: (event) =>
            set((s) => {
                if (event.id && event.id <= s.lastEventId) return s; // stream re-opened: skip what we already have
                const step = nodeToStep(event.node);
                const nodeStatus = { ...s.nodeStatus };
                if (STATUS[event.status]) nodeStatus[step] = STATUS[event.status];
                const patch = {
                    events: [...s.events, event].slice(-3000),
                    nodeStatus,
                    lastEventId: event.id || s.lastEventId,
                };
                if (event.node === 'planner_agent' && event.status === 'END' && event.data) {
                    patch.components = event.data.components || [];
                    patch.executionPlan = event.data.plan || [];
                }
                if (
                    event.node === 'security_agent' &&
                    event.status === 'START' &&
                    event.data?.scanners
                )
                    patch.scanners = event.data.scanners;
                if (event.node === 'pipeline_designer' && event.data?.spec) {
                    patch.spec = event.data.spec;
                    patch.executionPlan = event.data.plan || [];
                }
                return patch;
            }),
    }))
);

export default usePipelineStore;
