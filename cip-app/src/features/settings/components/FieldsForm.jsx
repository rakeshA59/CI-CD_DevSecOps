import { useEffect, useState } from 'react';
import { Input } from '@/shared/ui/input';

/**
 * Form for settings fields. Secret fields are never filled from the server: a saved secret shows
 * "saved – leave empty to keep"; typing a new value replaces it.
 * `selects` = { fieldName: [options] } renders a select instead of an input.
 */
export default function FieldsForm({ fields, selects = {}, onChange }) {
    const [values, setValues] = useState({});
    useEffect(() => {
        setValues(Object.fromEntries(fields.map((f) => [f.name, f.secret ? '' : f.value || ''])));
    }, [JSON.stringify(fields)]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => {
        onChange(values);
    }, [values]); // eslint-disable-line react-hooks/exhaustive-deps

    const set = (name, v) => setValues((s) => ({ ...s, [name]: v }));
    return (
        <div className="grid gap-3 md:grid-cols-2">
            {fields.map((f) => {
                const multiline = f.name === 'service_account_json' || f.name === 'env_vars';
                const placeholder = f.secret && f.saved ? 'saved – leave empty to keep' : '';
                return (
                    <label key={f.name} className={multiline ? 'md:col-span-2' : ''}>
                        <span className="text-muted-foreground mb-1 flex items-center gap-2 text-xs font-medium">
                            {f.label}
                            {f.secret && (
                                <span className="rounded border px-1 text-[10px]">
                                    {f.saved ? 'encrypted · saved' : 'encrypted'}
                                </span>
                            )}
                        </span>
                        {selects[f.name] ? (
                            <select
                                className="bg-background h-9 w-full rounded-md border px-2 text-sm"
                                value={values[f.name] || ''}
                                onChange={(e) => set(f.name, e.target.value)}
                            >
                                {selects[f.name].map((o) => (
                                    <option key={o} value={o}>
                                        {o.replaceAll('_', ' ')}
                                    </option>
                                ))}
                            </select>
                        ) : multiline ? (
                            <textarea
                                className="bg-background min-h-24 w-full rounded-md border p-2 font-mono text-xs"
                                placeholder={placeholder}
                                value={values[f.name] || ''}
                                onChange={(e) => set(f.name, e.target.value)}
                                autoComplete="off"
                                spellCheck={false}
                            />
                        ) : (
                            <Input
                                type={f.secret ? 'password' : 'text'}
                                placeholder={placeholder}
                                value={values[f.name] || ''}
                                onChange={(e) => set(f.name, e.target.value)}
                                autoComplete="off"
                            />
                        )}
                    </label>
                );
            })}
        </div>
    );
}
