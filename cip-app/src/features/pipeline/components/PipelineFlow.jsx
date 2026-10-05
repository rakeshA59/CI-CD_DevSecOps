import { ChevronRight } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { StatusIcon } from '@/shared/components/StatusBadge';
import usePipelineStore from '../store/usePipelineStore';

const AGENT_OF = {
    scan: 'security_agent',
    security_gate: 'security_agent',
    test_gate: 'test',
    package: 'image',
    container_gate: 'image',
};

/** The stages of this run, derived from the planner's components and execution plan. */
const DEFAULT_SCANS = [
    { name: 'semgrep', label: 'Semgrep (SAST)' },
    { name: 'trivy-fs', label: 'Trivy (dependencies + IaC)' },
    { name: 'gitleaks', label: 'Gitleaks (secrets)' },
];

/** Scanners of this run: from the finished run's steps, else announced live by the security agent. */
function scanList(run, scanners) {
    const done = Object.values(run?.steps || {}).filter((s) => s.id?.startsWith('scan.'));
    if (done.length) return done.map((s) => ({ name: s.id.slice(5), label: s.name }));
    return scanners.length ? scanners : DEFAULT_SCANS;
}

export function buildStages(components, plan, scans = DEFAULT_SCANS, guided = false) {
    const has = (n) => plan.some((s) => s.name === n);
    const lanes = (fn, list = components) => list.map((c) => ({ lane: c.name, steps: fn(c.name) }));
    const stages = [
        {
            title: 'Checkout',
            agent: 'Source Controller',
            lanes: [{ steps: [['checkout', 'Get the code']] }],
        },
        guided
            ? {
                  title: 'Discover + design',
                  agent: 'Tech-stack Analyst · Pipeline Architect',
                  lanes: [
                      {
                          steps: [
                              ['plan', 'Understand the tech stack'],
                              ['questionnaire', 'Questionnaire'],
                              ['design', 'Derive the pipeline'],
                          ],
                      },
                  ],
              }
            : {
                  title: 'Plan',
                  agent: 'Release Planner',
                  lanes: [{ steps: [['plan', 'Plan the pipeline']] }],
              },
        {
            title: 'Security',
            agent: 'Security Engineer',
            lanes: [
                {
                    steps: [
                        ...scans.map((s) => [`scan.${s.name}`, s.label]),
                        ['security_gate', 'Security gate'],
                    ],
                },
            ],
        },
    ];
    if (components.length) {
        stages.push({
            title: 'Build & test',
            agent: 'Build / Test Engineer',
            lanes: lanes((n) => [
                [`build.${n}`, 'Build'],
                [`test.${n}`, 'Unit tests'],
                [`test_gate.${n}`, 'Test gate'],
                [`package.${n}`, 'Package'],
            ]),
        });
        const deployable = components.filter((c) => c.deployable);
        if (deployable.length)
            stages.push({
                title: 'Containerise',
                agent: 'Release Engineer',
                lanes: lanes(
                    (n) => [
                        [`image.${n}`, 'Image + scan'],
                        [`container_gate.${n}`, 'Container gate'],
                    ],
                    deployable
                ),
            });
    }
    if (has('release_agent'))
        stages.push({
            title: 'Release',
            agent: 'Release Engineer',
            lanes: [{ steps: [['release', 'Push to registry']] }],
        });
    if (has('deploy_agent'))
        stages.push({
            title: 'Deploy (dev)',
            agent: 'Platform Engineer',
            lanes: [{ steps: [['deploy', 'docker run']] }],
        });
    if (has('functional_test_agent'))
        stages.push({
            title: 'Functional tests',
            agent: 'QA Engineer',
            lanes: [
                {
                    steps: [
                        ['functional', 'Functional tests'],
                        ['functional_gate', 'Functional gate'],
                    ],
                },
            ],
        });
    if (has('ui_test_agent'))
        stages.push({
            title: 'UI tests',
            agent: 'UI Test Engineer',
            lanes: [{ steps: [['ui_tests', 'Selenium browser tests'], ['ui_gate', 'UI gate']] }],
        });
    if (has('publish_tests_agent'))
        stages.push({
            title: 'Publish tests',
            agent: 'QA Lead',
            lanes: [{ steps: [['publish_tests', 'JUnit + HTML report']] }],
        });
    if (has('approval_gate') || has('uat_deploy_agent'))
        stages.push({
            title: 'UAT',
            agent: 'Reviewer · Platform Engineer',
            lanes: [
                {
                    steps: [
                        ...(has('approval_gate') ? [['approval', 'Human approval']] : []),
                        ['deploy_uat', 'Deploy to UAT'],
                    ],
                },
            ],
        });
    stages.push({
        title: 'Report',
        agent: 'Release Manager',
        lanes: [{ steps: [['report', 'Report + PDF']] }],
    });
    return stages;
}

function stepStatus(id, run, nodeStatus, live) {
    if (
        (id === 'questionnaire' && run?.status === 'WAITING_INPUT') ||
        (id === 'approval' && run?.status === 'WAITING_APPROVAL')
    )
        return 'waiting';
    const rec = run?.steps?.[id];
    if (rec) return rec.status;
    if (nodeStatus[id]) return nodeStatus[id];
    const [kind, comp] = id.split(/\.(.+)/);
    const agent = AGENT_OF[kind];
    const parent =
        agent === 'security_agent'
            ? nodeStatus.security_agent
            : agent
              ? nodeStatus[`${agent}.${comp}`]
              : null;
    if (parent === 'running' && live) return 'running';
    return parent && parent !== 'running' ? parent : 'pending';
}

export default function PipelineFlow() {
    const {
        run,
        nodeStatus,
        components,
        executionPlan,
        scanners,
        spec,
        live,
        selectedStep,
        selectStep,
    } = usePipelineStore();
    const guided = run?.mode === 'guided' || spec.length > 0;
    const stages = buildStages(
        components,
        guided && !spec.length ? [] : executionPlan,
        scanList(run, scanners),
        guided
    );
    return (
        <div className="flex items-stretch gap-1 overflow-x-auto pb-2">
            {stages.map((stage, i) => (
                <div key={stage.title} className="flex items-stretch">
                    {i > 0 && (
                        <ChevronRight className="text-muted-foreground mx-0.5 size-4 self-center" />
                    )}
                    <div className="bg-card w-52 shrink-0 rounded-lg border p-2">
                        <div className="mb-2 flex items-baseline justify-between px-1">
                            <span className="text-xs font-semibold tracking-wide uppercase">
                                {i + 1} · {stage.title}
                            </span>
                        </div>
                        <div className="text-muted-foreground px-1 pb-1 text-[11px]">
                            {stage.agent}
                        </div>
                        <div className="space-y-2">
                            {stage.lanes.map((lane, li) => (
                                <div key={li} className="space-y-1">
                                    {lane.lane && (
                                        <div className="text-primary px-1 text-[11px] font-medium">
                                            {lane.lane}
                                        </div>
                                    )}
                                    {lane.steps.map(([id, label]) => {
                                        const status = stepStatus(id, run, nodeStatus, live);
                                        const rec = run?.steps?.[id];
                                        return (
                                            <button
                                                key={id}
                                                type="button"
                                                onClick={() => selectStep(id)}
                                                className={cn(
                                                    'hover:bg-muted flex w-full items-start gap-2 rounded-md border border-l-4 px-2 py-1.5 text-left text-xs',
                                                    status === 'passed' && 'border-l-emerald-500',
                                                    ['failed', 'error'].includes(status) &&
                                                        'border-l-red-500',
                                                    status === 'blocked' &&
                                                        'border-dashed border-l-red-400 opacity-80',
                                                    ['skipped', 'warning', 'waiting'].includes(
                                                        status
                                                    ) && 'border-l-amber-500',
                                                    status === 'waiting' && 'animate-pulse',
                                                    status === 'running' && 'border-l-primary',
                                                    status === 'pending' && 'opacity-60',
                                                    selectedStep === id && 'ring-primary ring-2'
                                                )}
                                            >
                                                <StatusIcon
                                                    status={status}
                                                    className={cn(
                                                        status === 'passed' && 'text-emerald-500',
                                                        ['failed', 'error', 'blocked'].includes(
                                                            status
                                                        ) && 'text-red-500',
                                                        ['skipped', 'warning', 'waiting'].includes(
                                                            status
                                                        ) && 'text-amber-500',
                                                        status === 'running' && 'text-primary'
                                                    )}
                                                />
                                                <span className="min-w-0">
                                                    <span className="block font-medium">
                                                        {label}
                                                    </span>
                                                    {rec?.message && (
                                                        <span className="text-muted-foreground line-clamp-2 text-[11px]">
                                                            {rec.message}
                                                        </span>
                                                    )}
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}
