import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { Loader2, Wrench } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import StatusBadge from '@/shared/components/StatusBadge';
import { getScanners } from '@/features/pipeline/services/PipelineService';
import { getMcpHealth, repairScanner, saveSonarqube } from '../services/SettingsService';
import FieldsForm from './FieldsForm';

/** Scanners: MCP server status, every scanner's install state (with Repair) and the SonarQube connection. */
export default function ScannersSettings({ sonarqube, reload }) {
    const [scanners, setScanners] = useState([]);
    const [mcp, setMcp] = useState({});
    const [repairing, setRepairing] = useState('');
    const sonar = useRef({});
    const load = () => {
        getScanners()
            .then((d) => setScanners(d.scanners))
            .catch(() => {});
        getMcpHealth()
            .then(setMcp)
            .catch(() => {});
    };
    useEffect(load, []);

    const repair = async (name) => {
        setRepairing(name);
        const res = await repairScanner(name).catch((e) => ({ ok: false, message: e.message }));
        (res.ok ? toast.success : toast.error)(`${name}: ${res.message}`);
        setRepairing('');
        load();
    };
    const save = async () => {
        await saveSonarqube(sonar.current);
        toast.success('SonarQube connection saved');
        reload();
        load();
    };

    return (
        <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="font-medium">MCP servers</span>
                {Object.entries(mcp).map(([name, s]) => (
                    <StatusBadge
                        key={name}
                        status={s.up ? 'passed' : 'failed'}
                        label={`${name} ${s.url.replace(/^https?:\/\//, '').replace(/\/sse$/, '')} ${s.up ? 'up' : 'down'}`}
                    />
                ))}
                <span className="text-muted-foreground text-xs">
                    The API starts them; when one is down the agents run the same tools directly.
                </span>
            </div>

            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {scanners.map((s) => (
                    <div
                        key={s.name}
                        className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
                    >
                        <div className="min-w-0 flex-1">
                            <div className="truncate font-medium">{s.label}</div>
                            <div className="text-muted-foreground text-xs">{s.category}</div>
                        </div>
                        {!s.configured ? (
                            <StatusBadge status="skipped" label="not configured" />
                        ) : s.installed ? (
                            <StatusBadge status="passed" label="installed" />
                        ) : (
                            <StatusBadge status="warning" label="not installed" />
                        )}
                        {s.repairable && (
                            <Button
                                size="sm"
                                variant="outline"
                                className="h-7 gap-1 px-2"
                                disabled={!!repairing}
                                title="(Re)install into cip-api/.scanners"
                                onClick={() => repair(s.name)}
                            >
                                {repairing === s.name ? (
                                    <Loader2 className="size-3.5 animate-spin" />
                                ) : (
                                    <Wrench className="size-3.5" />
                                )}
                                {s.installed ? 'Repair' : 'Install'}
                            </Button>
                        )}
                    </div>
                ))}
            </div>

            <div className="space-y-3 rounded-lg border p-3">
                <div className="font-medium">SonarQube</div>
                <p className="text-muted-foreground text-xs">
                    Needs a SonarQube server. Local one:{' '}
                    <code>docker run -d --name sonarqube -p 9000:9000 sonarqube:community</code> →
                    open http://localhost:9000, create a token, save both here. The scanner CLI runs
                    from Docker when it is not installed. Once set, the agent picks SonarQube for
                    SAST.
                </p>
                <FieldsForm fields={sonarqube} onChange={(v) => (sonar.current = v)} />
                <Button onClick={save}>Save SonarQube</Button>
            </div>
        </div>
    );
}
