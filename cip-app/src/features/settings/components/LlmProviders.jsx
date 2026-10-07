import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import StatusBadge from '@/shared/components/StatusBadge';
import { getProviders, setDefaultProvider, testProvider } from '../services/LlmService';

/** LLM providers: which are configured in .env, test a provider, choose the default. */
export default function LlmProviders() {
    const [data, setData] = useState({ default: '', providers: [] });
    const [testing, setTesting] = useState('');
    const [results, setResults] = useState({});

    const load = () =>
        getProviders()
            .then(setData)
            .catch((e) => toast.error(e.message));
    useEffect(() => {
        load();
    }, []);

    const makeDefault = async (id) => {
        await setDefaultProvider(id);
        toast.success('Default provider saved');
        load();
    };

    const test = async (id) => {
        setTesting(id);
        const res = await testProvider(id).catch((e) => ({ ok: false, message: e.message }));
        setResults((r) => ({ ...r, [id]: res }));
        setTesting('');
    };

    return (
        <div className="space-y-3">
            <p className="text-muted-foreground text-sm">
                Keys are read from <code>cip-api/.env</code> (never shown here). The default is
                preselected on the run form; you can still pick another provider per run.
            </p>
            {data.providers.map((p) => (
                <div key={p.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
                    <div className="min-w-48">
                        <div className="font-semibold">{p.label}</div>
                        <div className="text-muted-foreground text-xs">
                            {p.model || (p.id === 'none' ? 'rules only' : '')}
                        </div>
                    </div>
                    {p.id !== 'none' &&
                        (p.configured ? (
                            <StatusBadge status="passed" label="configured" />
                        ) : (
                            <span className="text-muted-foreground text-xs">
                                set {p.missing.join(', ')}
                            </span>
                        ))}
                    {data.default === p.id && <StatusBadge status="running" label="default" />}
                    {results[p.id] && (
                        <span className="flex items-center gap-1 text-xs">
                            {results[p.id].ok ? (
                                <CheckCircle2 className="size-4 text-emerald-500" />
                            ) : (
                                <XCircle className="size-4 text-red-500" />
                            )}
                            {results[p.id].message}
                        </span>
                    )}
                    <div className="ml-auto flex gap-2">
                        {p.id !== 'none' && (
                            <Button
                                variant="outline"
                                size="sm"
                                disabled={!p.configured || testing === p.id}
                                onClick={() => test(p.id)}
                            >
                                {testing === p.id && <Loader2 className="size-4 animate-spin" />}{' '}
                                Test
                            </Button>
                        )}
                        <Button
                            size="sm"
                            disabled={data.default === p.id || (!p.configured && p.id !== 'none')}
                            onClick={() => makeDefault(p.id)}
                        >
                            Make default
                        </Button>
                    </div>
                </div>
            ))}
        </div>
    );
}
