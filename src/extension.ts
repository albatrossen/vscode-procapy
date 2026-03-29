
import * as vscode from 'vscode';
import * as path from 'path';
import * as cp from 'child_process';

let persistentChild: cp.ChildProcess | undefined;
let persistentChildExited = false;
let persistentPythonPath: string | undefined;
let requestQueue: Promise<unknown> = Promise.resolve();

type ProcaResponse = {
    type: 'RES' | 'ERR' | 'ALT' | 'NOP';
    contents: string;
};

function enqueueRequest<T>(fn: () => Promise<T>): Promise<T>
{
    let next = requestQueue.then(fn, fn) as Promise<T>;
    requestQueue = next.catch(() => undefined);
    return next;
}

async function startPythonProcess(python_path: string, proca_path: string): Promise<cp.ChildProcess>
{
    if (persistentChild && !persistentChildExited && persistentPythonPath === python_path)
    {
        return persistentChild;
    }

    if (persistentChild && !persistentChildExited)
    {
        persistentChild.kill();
    }

    persistentPythonPath = python_path;
    persistentChildExited = false;
    persistentChild = cp.spawn(python_path, [proca_path], { stdio: ['pipe', 'pipe', 'pipe'] });

    persistentChild.on('error', () =>
    {
        persistentChildExited = true;
    });
    persistentChild.on('close', () =>
    {
        persistentChildExited = true;
    });
    persistentChild.on('exit', () =>
    {
        persistentChildExited = true;
    });

    const startupCode = getStartupCode();
    await sendCommand(persistentChild, `EVAL 0 0`, startupCode);

    return persistentChild;
}

function getStartupCode(): string
{
    let startupCode = vscode.workspace.getConfiguration('procapy').get<string>('startupCode');
    if (typeof startupCode === 'string' && startupCode.length > 0)
    {
        return startupCode;
    }
    return "";
}

function sendCommand(child: cp.ChildProcess, command: string, input: string): Promise<ProcaResponse>
{
    return new Promise((resolve, reject) =>
    {
        let buffer = Buffer.alloc(0);
        let finished = false;

        const cleanupListeners = () =>
        {
            if (child.stdout)
            {
                child.stdout.off('data', onStdout);
            }
            if (child.stderr)
            {
                child.stderr.off('data', onStderr);
            }
            child.off('error', onErrorOrClose);
            child.off('close', onErrorOrClose);
        };

        const parseResponse = (): ProcaResponse | null =>
        {
            let headerEnd = buffer.indexOf('\n');
            if (headerEnd === -1)
            {
                return null;
            }

            let header = buffer.slice(0, headerEnd).toString().trim();
            let match = header.match(/^(RES|ERR|ALT|NOP) (\d+)$/);
            if (!match)
            {
                throw new Error(`Unexpected response header: ${header}`);
            }

            let size = parseInt(match[2], 10);
            let remaining = buffer.slice(headerEnd + 1);
            if (remaining.length < size + 1)
            {
                return null;
            }

            if (remaining[size] !== 0x0a)
            {
                throw new Error('Response missing terminating line feed');
            }

            let contents = remaining.slice(0, size).toString();
            buffer = remaining.slice(size + 1);
            return { type: match[1] as 'RES' | 'ERR' | 'ALT' | 'NOP', contents };
        };

        const onStdout = (chunk: Buffer | string) =>
        {
            let chunkBuffer = chunk instanceof Buffer ? chunk : Buffer.from(chunk);
            buffer = Buffer.concat([buffer, chunkBuffer] as any) as Buffer;
            try
            {
                let result = parseResponse();
                if (result !== null && !finished)
                {
                    finished = true;
                    cleanupListeners();
                    resolve(result);
                }
            }
            catch (err)
            {
                finished = true;
                cleanupListeners();
                reject(err);
            }
        };

        const onStderr = (chunk: Buffer | string) =>
        {
            // ignore stderr for protocol parsing, but preserve it for debugging if needed
        };

        const onErrorOrClose = (codeOrError: any) =>
        {
            if (finished)
            {
                return;
            }
            finished = true;
            cleanupListeners();
            reject(new Error(`Python process exited before response was complete${typeof codeOrError === 'number' ? ` with code ${codeOrError}` : ''}`));
        };

        if (child.stdout)
        {
            child.stdout.on('data', onStdout);
        }
        if (child.stderr)
        {
            child.stderr.on('data', onStderr);
        }
        child.on('error', onErrorOrClose);
        child.on('close', onErrorOrClose);

        child.stdin!.write(`${command} ${Buffer.byteLength(input, 'utf8')}\n`);
        child.stdin!.write(`${input}\n`);
    });
}

async function evaluate(input: string, proca_path: string, python_path: string, selectionIndex: number, selectionCount: number, conversion: string): Promise<ProcaResponse>
{
    return enqueueRequest(async () =>
    {
        const child = await startPythonProcess(python_path, proca_path);
        const sanitizedConversion = conversion.replace(/\r?\n/g, ' ').trim();
        return sendCommand(child, `EVAL ${selectionIndex} ${selectionCount} ${sanitizedConversion}`, input);
    });
}

function get_python_path()
{
    var python_paths: string[] = ['python3', 'python'];
    let python_configured_path = vscode.workspace.getConfiguration('python', null).get('pythonPath');
    if (typeof python_configured_path === "string")
    {
        python_paths.unshift(python_configured_path);
    }
    for (var python_path of python_paths)
    {
        try
        {
            cp.execFileSync(python_path, ['--version']);
            return python_path;
        }
        catch (e) {}
    }
    vscode.window.showErrorMessage(
        'Python executable not found, make sure "python3" or "python" is in the path, ' +
        'or install the Python extension to define a custom location of python.');
    return undefined;
}

async function process(proca_path: string, args?: { conversion?: string })
{
    let editor = vscode.window.activeTextEditor;
    let python_path = get_python_path();

    if (editor && python_path !== undefined)
    {
        let edits: Array<{
            selection: vscode.Selection;
            text: string;
        }> = [];

        let selections = editor.selections.slice().sort((a, b) =>
        {
            if (a.start.line !== b.start.line)
            {
                return a.start.line - b.start.line;
            }
            return a.start.character - b.start.character;
        });

        let n = 0;
        let m = selections.length;
        let conversion = args?.conversion ?? '';
        for (const selection of selections)
        {
            let expression: string | undefined;
            if (!selection.isEmpty)
            {
                expression = editor.document.getText(selection);
            }
            else
            {
                expression = editor.document.lineAt(selection.active.line).text;
            }

            if (expression && expression.trim().length > 0)
            {
                let inline = expression.trimEnd().endsWith("=");
                let response = await evaluate(inline?expression.trimEnd().slice(0,-1):expression, proca_path, python_path, n, m, conversion);
                let replacement: string;
                if (response.type === 'NOP')
                {
                    continue;
                }
                if (response.type === 'ALT')
                {
                    let altSelection = await showAltQuickPick(response.contents);
                    if (altSelection === undefined)
                    {
                        break;
                    }
                    conversion = altSelection.label;
                    replacement = altSelection.description ?? ''
                }
                else
                {
                    replacement = response.contents;
                }

                if (selection.isEmpty && !inline)
                {
                    "( " + JSON.stringify("") + ")"
                    response = await evaluate(`procapy_hook_expandline(${JSON.stringify(expression)}, ${JSON.stringify(replacement)})`, proca_path, python_path, n, m, conversion);
                    if (response.type !== "RES" && response.type !== "ERR")
                    {
                        continue;
                    }
                    replacement = response.contents;
                }
                edits.push({ selection, text: inline?expression + replacement : replacement });
            }

            n += 1;
        }

        const activeEditor = editor;
        await activeEditor.edit((builder) =>
        {
            for (const edit of edits)
            {
                if (edit.selection.isEmpty)
                {
                    let lineRange = activeEditor!.document.lineAt(edit.selection.active.line).range;
                    builder.replace(lineRange, edit.text);
                }
                else
                {
                    builder.replace(edit.selection, edit.text);
                }
            }
        });
    }
}

async function capture(proca_path: string, args?: { data?: string })
{
    let editor = vscode.window.activeTextEditor;
    let python_path = get_python_path();

    if (!editor || python_path === undefined)
    {
        return;
    }

    let key = args?.data ?? 'data';
    let selections = editor.selections.slice();
    let document = editor.document;
    let payload: Record<string, unknown>;

    if (selections.length === 0 || (selections.length === 1 && selections[0].isEmpty))
    {
        payload = { [key]: document.getText() };
    }
    else if (selections.length === 1)
    {
        payload = { [key]: document.getText(selections[0]) };
    }
    else
    {
        payload = { [key]: selections.map((selection) => document.getText(selection)) };
    }

    const jsonPayload = JSON.stringify(payload);
    const child = await startPythonProcess(python_path, proca_path);
    const response = await sendCommand(child, "SET", jsonPayload);
    if (response.type === 'NOP')
    {
        return;
    }
    if (response.type === 'ERR')
    {
        vscode.window.showErrorMessage(response.contents);
    }
}

export function activate(context: vscode.ExtensionContext)
{
    let proca_path = path.join(context.extensionPath, "proca.py");

    context.subscriptions.push(
        vscode.commands.registerCommand(
            'procapy.calculate', (args?: { conversion?: string }) => { process(proca_path, args); }
        )
    );
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'procapy.capture', (args?: { data?: string }) => { capture(proca_path, args); }
        )
    );
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'procapy.stop', deactivate
        )
    );
}

function parseAltOptions(contents: string): Array<vscode.QuickPickItem>
{
    let parsed = JSON.parse(contents);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
    {
        return Object.entries(parsed).map(([label, value]) => ({
            label,
            description: value === undefined || value === null ? '' : String(value),
        }));
    }
    throw new Error(`Unexpected alt response: ${contents}`);
}

async function showAltQuickPick(contents: string): Promise<vscode.QuickPickItem | undefined>
{
    let items = parseAltOptions(contents);
    if (items.length === 0)
    {
        return undefined;
    }
    return await vscode.window.showQuickPick(items, {
        placeHolder: 'Select an alternate result',
    });
}

export function deactivate()
{
    if (persistentChild && !persistentChild.killed)
    {
        persistentChild.kill();
    }
    persistentChild = undefined;
}
