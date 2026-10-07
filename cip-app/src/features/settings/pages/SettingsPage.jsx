import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { Bot, ChevronDown, ChevronRight, Cloud, Server, ShieldCheck } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import StatusBadge from '@/shared/components/StatusBadge';
import FieldsForm from '../components/FieldsForm';
import LlmProviders from '../components/LlmProviders';
import ScannersSettings from '../components/ScannersSettings';
import { deleteInfra, getSettings, saveEnvironment, saveInfra } from '../services/SettingsService';

/** A collapsible settings block. */
function Section({ icon: Icon, title, hint, badge, defaultOpen = false, children }) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div className="bg-card rounded-xl border">
            <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
                onClick={() => setOpen((o) => !o)}
            >
                {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                <Icon className="text-primary size-5" />
                <span className="font-semibold">{title}</span>
                {badge}
                {hint && <span className="text-muted-foreground ml-auto text-xs">{hint}</span>}
            </button>
            {open && <div className="border-t px-4 py-4">{children}</div>}
        </div>
    );
}

/** AWS / Azure / GCP: pick one, then its credentials (stored encrypted, never shown again). */
function InfraProviders({ infra, reload }) {
    const [provider, setProvider] = useState(infra.selected || 'aws');
    const values = useRef({});
    const p = infra.providers[provider];
    const save = async () => {
        await saveInfra(provider, values.current);
        toast.success(`${p.label} credentials saved (encrypted)`);
        reload();
    };
    const remove = async () => {
        await deleteInfra(provider);
        toast.success(`${p.label} credentials removed`);
        reload();
    };
    return (
        <div className="space-y-4">
            <p className="text-muted-foreground text-sm">
                Cloud credentials for the deploy stages. Secret values are encrypted before they are
                stored and are never sent back to the browser. Today the pipeline deploys to local
                Docker – these are recorded for the cloud-deploy stage.
            </p>
            <div className="flex flex-wrap gap-2">
                {Object.entries(infra.providers).map(([id, v]) => (
                    <button
                        key={id}
                        type="button"
                        onClick={() => setProvider(id)}
                        className={cn(
                            'flex items-center gap-2 rounded-lg border px-4 py-2 text-sm',
                            provider === id
                                ? 'border-primary bg-primary/10 font-semibold'
                                : 'text-muted-foreground'
                        )}
                    >
                        {v.label}
                        {v.fields.some((f) => f.saved || f.value) && (
                            <StatusBadge status="passed" label="saved" />
                        )}
                        {infra.selected === id && <StatusBadge status="running" label="selected" />}
                    </button>
                ))}
            </div>
            <FieldsForm fields={p.fields} onChange={(v) => (values.current = v)} />
            <div className="flex gap-2">
                <Button onClick={save}>Save {p.label}</Button>
                <Button variant="outline" onClick={remove}>
                    Remove
                </Button>
            </div>
        </div>
    );
}

/** One environment (dev / test / prod): deploy target, provider, registry, URLs, env variables. */
function Environment({ name, env, targets, providers, reload }) {
    const values = useRef({});
    const save = async () => {
        await saveEnvironment(name, values.current);
        toast.success(`${env.label} saved`);
        reload();
    };
    return (
        <div className="space-y-4">
            <p className="text-muted-foreground text-sm">{env.used}</p>
            <FieldsForm
                fields={env.fields}
                selects={{ target: targets, infra_provider: providers }}
                onChange={(v) => (values.current = v)}
            />
            <Button onClick={save}>Save {env.label.toLowerCase()}</Button>
        </div>
    );
}

export default function SettingsPage() {
    const [data, setData] = useState(null);
    const load = () =>
        getSettings()
            .then(setData)
            .catch((e) => toast.error(e.message));
    useEffect(() => {
        load();
    }, []);

    return (
        <div className="w-full space-y-3">
            <h1 className="text-xl font-bold">Settings</h1>
            <Section icon={Bot} title="LLM" hint="model in use · + Add model" defaultOpen>
                <LlmProviders />
            </Section>
            {data && (
                <>
                    <Section
                        icon={ShieldCheck}
                        title="Scanners"
                        hint="MCP servers · install / repair · SonarQube"
                    >
                        <ScannersSettings sonarqube={data.sonarqube} reload={load} />
                    </Section>
                    <Section
                        icon={Cloud}
                        title="Infra providers"
                        hint="AWS · Azure · Google Cloud"
                        badge={
                            data.infra.selected && (
                                <StatusBadge
                                    status="passed"
                                    label={data.infra.providers[data.infra.selected]?.label}
                                />
                            )
                        }
                    >
                        <InfraProviders infra={data.infra} reload={load} />
                    </Section>
                    {Object.entries(data.environments).map(([name, env]) => (
                        <Section
                            key={name}
                            icon={Server}
                            title={env.label}
                            hint={env.used.split(' – ')[0]}
                        >
                            <Environment
                                name={name}
                                env={env}
                                targets={data.targets}
                                providers={data.providers}
                                reload={load}
                            />
                        </Section>
                    ))}
                </>
            )}
        </div>
    );
}
