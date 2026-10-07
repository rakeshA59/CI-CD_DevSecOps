import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { CheckCircle2, Loader2, Plus, X, XCircle } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import StatusBadge from '@/shared/components/StatusBadge';
import FieldsForm from './FieldsForm';
import {
    getProviders,
    removeProvider,
    saveProvider,
    setDefaultProvider,
    testProvider,
} from '../services/LlmService';

/**
 * LLM providers: the one in use (the default, preselected on the run form) is shown; "+ Add model" adds or
 * switches to another provider. Keys typed here are stored encrypted (a value in cip-api/.env still wins).
 */
export default function LlmProviders() {
    const [data, setData] = useState({ default: '', providers: [] });
    const [adding, setAdding] = useState(false);
    const [pick, setPick] = useState('');
    const [busy, setBusy] = useState('');
    const [result, setResult] = useState(null);
    const values = useRef({});

    const load = () =>
        getProviders()
            .then(setData)
            .catch((e) => toast.error(e.message));
    useEffect(() => {
        load();
    }, []);

    const current = data.providers.find((p) => p.id === data.default);
    const others = data.providers.filter((p) => p.id !== data.default);
    const chosen = data.providers.find((p) => p.id === pick);

    const test = async (id) => {
        setBusy(`test:${id}`);
        setResult({
            id,
            ...(await testProvider(id).catch((e) => ({ ok: false, message: e.message }))),
        });
        setBusy('');
    };
    const makeDefault = async (id) => {
        await setDefaultProvider(id);
        toast.success('Now in use for new runs');
        setAdding(false);
        setPick('');
        load();
    };
    const save = async (andUse) => {
        setBusy('save');
        try {
            if (chosen.fields?.length) await saveProvider(chosen.id, values.current);
            if (andUse) await makeDefault(chosen.id);
            else {
                toast.success(`${chosen.label} saved`);
                load();
            }
        } catch (e) {
            toast.error(e.message);
        } finally {
            setBusy('');
        }
    };
    const remove = async (id) => {
        await removeProvider(id);
        toast.success('Keys saved in Settings removed');
        load();
    };

    const testResult = (id) =>
        result?.id === id && (
            <span className="flex items-center gap-1 text-xs">
                {result.ok ? (
                    <CheckCircle2 className="size-4 text-emerald-500" />
                ) : (
                    <XCircle className="size-4 text-red-500" />
                )}
                {result.message}
            </span>
        );

    return (
        <div className="space-y-3">
            <p className="text-muted-foreground text-sm">
                The model the agents use for new runs (you can still pick another one per run). Keys
                are never shown; keys added here are stored encrypted, keys in{' '}
                <code>cip-api/.env</code> win.
            </p>

            {current && (
                <div className="border-primary/40 flex flex-wrap items-center gap-3 rounded-lg border p-3">
                    <div className="min-w-48">
                        <div className="font-semibold">{current.label}</div>
                        <div className="text-muted-foreground text-xs">
                            {current.model || (current.id === 'none' ? 'rules only' : '')}
                            {current.source && ` · keys from ${current.source}`}
                        </div>
                    </div>
                    <StatusBadge status="running" label="in use" />
                    {testResult(current.id)}
                    {current.id !== 'none' && (
                        <Button
                            className="ml-auto"
                            variant="outline"
                            size="sm"
                            disabled={busy === `test:${current.id}`}
                            onClick={() => test(current.id)}
                        >
                            {busy === `test:${current.id}` && (
                                <Loader2 className="size-4 animate-spin" />
                            )}
                            Test
                        </Button>
                    )}
                </div>
            )}

            {!adding ? (
                <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
                    <Plus className="size-4" /> Add model
                </Button>
            ) : (
                <div className="space-y-3 rounded-lg border p-3">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">Add or switch model</span>
                        <Button
                            className="ml-auto"
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                                setAdding(false);
                                setPick('');
                            }}
                        >
                            <X className="size-4" />
                        </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {others.map((p) => (
                            <button
                                key={p.id}
                                type="button"
                                onClick={() => setPick(p.id)}
                                className={`rounded-lg border px-3 py-1.5 text-sm ${
                                    pick === p.id
                                        ? 'border-primary bg-primary/10 font-semibold'
                                        : 'text-muted-foreground'
                                }`}
                            >
                                {p.label}
                                {p.configured && p.id !== 'none' && ' ✓'}
                            </button>
                        ))}
                    </div>
                    {chosen && (
                        <div className="space-y-3">
                            {chosen.configured && chosen.id !== 'none' && (
                                <p className="text-muted-foreground text-xs">
                                    Already configured ({chosen.model}
                                    {chosen.source && `, keys from ${chosen.source}`}) – change the
                                    keys below or just use it.
                                </p>
                            )}
                            {chosen.fields?.length > 0 && (
                                <FieldsForm
                                    fields={chosen.fields}
                                    onChange={(v) => (values.current = v)}
                                />
                            )}
                            <div className="flex flex-wrap items-center gap-2">
                                {chosen.fields?.length > 0 && (
                                    <Button
                                        variant="outline"
                                        disabled={!!busy}
                                        onClick={() => save(false)}
                                    >
                                        Save
                                    </Button>
                                )}
                                <Button disabled={!!busy} onClick={() => save(true)}>
                                    {busy === 'save' && <Loader2 className="size-4 animate-spin" />}
                                    {chosen.fields?.length ? 'Save and use' : 'Use'}
                                </Button>
                                {chosen.configured && chosen.id !== 'none' && (
                                    <Button
                                        variant="outline"
                                        disabled={busy === `test:${chosen.id}`}
                                        onClick={() => test(chosen.id)}
                                    >
                                        Test
                                    </Button>
                                )}
                                {chosen.source === 'settings' && (
                                    <Button variant="ghost" onClick={() => remove(chosen.id)}>
                                        Remove saved keys
                                    </Button>
                                )}
                                {testResult(chosen.id)}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
