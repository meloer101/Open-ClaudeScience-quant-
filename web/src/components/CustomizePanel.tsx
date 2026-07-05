import { useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteMcpServer,
  deleteSkill,
  importMcpServers,
  importSkill,
  listMcpServers,
  listSkills,
  saveMcpServer,
  testMcpServer,
  toggleMcpServer,
  toggleSkill,
  type McpServerRecord,
  type SkillRecord,
} from "../api/client";

interface CustomizePanelProps {
  onClose: () => void;
}

type Tab = "skills" | "mcp";

export function CustomizePanel({ onClose }: CustomizePanelProps) {
  const [tab, setTab] = useState<Tab>("skills");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="flex h-[min(720px,90vh)] w-full max-w-4xl flex-col rounded-xl border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">自定义 / Customize</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            Close
          </button>
        </div>
        <div className="flex border-b border-slate-200 px-5 pt-3">
          <TabButton active={tab === "skills"} onClick={() => setTab("skills")}>
            Skills
          </TabButton>
          <TabButton active={tab === "mcp"} onClick={() => setTab("mcp")}>
            MCP (Connectors)
          </TabButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{tab === "skills" ? <SkillsTab /> : <McpTab />}</div>
      </div>
    </div>
  );
}

function TabButton({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`border-b-2 px-3 pb-2 text-sm font-medium ${
        active ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"
      }`}
    >
      {children}
    </button>
  );
}

function SkillsTab() {
  const queryClient = useQueryClient();
  const [skillMd, setSkillMd] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { data: skills = [], isLoading } = useQuery({ queryKey: ["config-skills"], queryFn: listSkills });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["config-skills"] });
  const addMutation = useMutation({
    mutationFn: importSkill,
    onSuccess: () => {
      setSkillMd("");
      setError(null);
      void refresh();
    },
    onError: (err) => setError(String(err)),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (skillMd.trim()) addMutation.mutate(skillMd);
        }}
        className="rounded-lg border border-slate-200 p-3"
      >
        <div className="text-sm font-medium text-slate-900">Add skill</div>
        <textarea
          value={skillMd}
          onChange={(event) => setSkillMd(event.target.value)}
          placeholder="Paste SKILL.md"
          className="mt-3 h-56 w-full resize-none rounded-md border border-slate-300 px-3 py-2 font-mono text-xs focus:border-slate-500 focus:outline-none"
        />
        {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
        <button
          type="submit"
          disabled={!skillMd.trim() || addMutation.isPending}
          className="mt-3 w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-200 disabled:text-slate-500"
        >
          {addMutation.isPending ? "Adding..." : "+ Add skill"}
        </button>
      </form>
      <div className="overflow-hidden rounded-lg border border-slate-200">
        {isLoading && <div className="p-4 text-sm text-slate-500">Loading...</div>}
        {!isLoading && skills.length === 0 && <div className="p-4 text-sm text-slate-500">No skills found.</div>}
        {skills.map((skill) => (
          <SkillRow key={skill.name} skill={skill} onChanged={refresh} />
        ))}
      </div>
    </div>
  );
}

function SkillRow({ skill, onChanged }: { skill: SkillRecord; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const canDelete = skill.scope === "user";
  const change = async (enabled: boolean) => {
    setBusy(true);
    try {
      await toggleSkill(skill.name, enabled);
      await onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid grid-cols-[1fr_auto] gap-3 border-b border-slate-100 p-3 last:border-b-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <div className="truncate text-sm font-medium text-slate-900">{skill.name}</div>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">{skill.scope}</span>
        </div>
        <div className="mt-1 text-xs text-slate-600">{skill.description}</div>
        {skill.triggers.length > 0 && <div className="mt-1 truncate text-[11px] text-slate-400">{skill.triggers.join(", ")}</div>}
      </div>
      <div className="flex items-center gap-2">
        <Toggle checked={skill.enabled} disabled={busy} onChange={change} />
        {canDelete && (
          <button
            type="button"
            onClick={async () => {
              setBusy(true);
              try {
                await deleteSkill(skill.name);
                await onChanged();
              } finally {
                setBusy(false);
              }
            }}
            className="rounded-md px-2 py-1 text-xs text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

function McpTab() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { data: servers = [], isLoading } = useQuery({ queryKey: ["config-mcp"], queryFn: listMcpServers });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["config-mcp"] });

  const addServer = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await saveMcpServer({ name: name.trim(), command: command.trim(), args: splitArgs(args) });
      setName("");
      setCommand("");
      setArgs("");
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  };

  const pasteJson = async () => {
    setError(null);
    try {
      await importMcpServers(JSON.parse(jsonText));
      setJsonText("");
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
      <div className="space-y-4">
        <form onSubmit={addServer} className="rounded-lg border border-slate-200 p-3">
          <div className="text-sm font-medium text-slate-900">Add server</div>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="name"
            className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          <input
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="command"
            className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          <input
            value={args}
            onChange={(event) => setArgs(event.target.value)}
            placeholder="args, space separated"
            className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!name.trim() || !command.trim()}
            className="mt-3 w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-200 disabled:text-slate-500"
          >
            + Add server
          </button>
        </form>
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-sm font-medium text-slate-900">Paste JSON</div>
          <textarea
            value={jsonText}
            onChange={(event) => setJsonText(event.target.value)}
            placeholder='{"mcpServers":{"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","."]}}}'
            className="mt-3 h-40 w-full resize-none rounded-md border border-slate-300 px-3 py-2 font-mono text-xs focus:border-slate-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => void pasteJson()}
            disabled={!jsonText.trim()}
            className="mt-3 w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-200 disabled:text-slate-500"
          >
            Import JSON
          </button>
        </div>
        {error && <div className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</div>}
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200">
        {isLoading && <div className="p-4 text-sm text-slate-500">Loading...</div>}
        {!isLoading && servers.length === 0 && <div className="p-4 text-sm text-slate-500">No MCP servers configured.</div>}
        {servers.map((server) => (
          <McpRow key={server.name} server={server} onChanged={refresh} />
        ))}
      </div>
    </div>
  );
}

function McpRow({ server, onChanged }: { server: McpServerRecord; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const target = server.url || [server.command, ...server.args].filter(Boolean).join(" ");
  const canDelete = server.scope === "user" || server.scope === "project";
  const change = async (enabled: boolean) => {
    setBusy(true);
    try {
      await toggleMcpServer(server.name, enabled);
      await onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="border-b border-slate-100 p-3 last:border-b-0">
      <div className="grid grid-cols-[1fr_auto] gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${server.status === "configured" ? "bg-emerald-500" : "bg-amber-400"}`} />
            <div className="truncate text-sm font-medium text-slate-900">{server.name}</div>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">{server.type}</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">{server.scope}</span>
            {server.status !== "configured" && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] uppercase text-amber-700">{server.status}</span>
            )}
          </div>
          <div className="mt-1 truncate font-mono text-xs text-slate-500">{target}</div>
          <div className="mt-1 text-[11px] text-slate-400">
            {server.enabledTools.length ? `${server.enabledTools.length} enabled tool(s)` : "all read-only tools"}
          </div>
          {testResult && <div className="mt-2 rounded bg-slate-50 px-2 py-1 text-xs text-slate-600">{testResult}</div>}
        </div>
        <div className="flex items-start gap-2">
          <Toggle checked={server.enabled} disabled={busy} onChange={change} />
          <button
            type="button"
            onClick={async () => {
              setTestResult("Testing...");
              const result = await testMcpServer(server.name);
              if (result.status === "ok") {
                setTestResult(`Tools: ${result.tools.join(", ") || "none"}`);
              } else if (result.status === "needs-authorization") {
                setTestResult(`Needs authorization: ${result.error || "authorize this server"}`);
              } else {
                setTestResult(result.error || "Failed");
              }
            }}
            className="rounded-md px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
          >
            Test
          </button>
          {canDelete && (
            <button
              type="button"
              onClick={async () => {
                setBusy(true);
                try {
                  await deleteMcpServer(server.name, server.scope);
                  await onChanged();
                } finally {
                  setBusy(false);
                }
              }}
              className="rounded-md px-2 py-1 text-xs text-red-600 hover:bg-red-50"
            >
              Delete
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void | Promise<void>;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={checked}
      onClick={() => void onChange(!checked)}
      className={`h-6 w-11 rounded-full p-0.5 transition-colors disabled:opacity-60 ${checked ? "bg-slate-900" : "bg-slate-200"}`}
    >
      <span className={`block h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0"}`} />
    </button>
  );
}

function splitArgs(value: string): string[] {
  return value.split(/\s+/).map((item) => item.trim()).filter(Boolean);
}
