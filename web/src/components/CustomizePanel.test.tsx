import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { testMcpServer } from "../api/client";
import { CustomizePanel } from "./CustomizePanel";

vi.mock("../api/client", () => ({
  listSkills: vi.fn().mockResolvedValue([
    {
      name: "reviewer-weak-triage",
      description: "Triage weak reviewer verdicts",
      triggers: ["WEAK"],
      path: "/tmp/skill/SKILL.md",
      scope: "project",
      enabled: true,
      attachments: [],
    },
  ]),
  listMcpServers: vi.fn().mockResolvedValue([
    {
      name: "filesystem",
      type: "stdio",
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-filesystem", "."],
      env: {},
      url: "",
      enabledTools: [],
      allowWrite: false,
      scope: "user",
      source: "/tmp/mcp.json",
      enabled: true,
      status: "configured",
      tools: [],
    },
  ]),
  importSkill: vi.fn(),
  toggleSkill: vi.fn().mockResolvedValue({ status: "ok" }),
  deleteSkill: vi.fn(),
  saveMcpServer: vi.fn(),
  importMcpServers: vi.fn(),
  toggleMcpServer: vi.fn().mockResolvedValue({ status: "ok" }),
  deleteMcpServer: vi.fn(),
  testMcpServer: vi.fn().mockResolvedValue({ status: "ok", tools: ["read_file"] }),
}));

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CustomizePanel onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

test("renders skills and switches to MCP connectors", async () => {
  const user = userEvent.setup();
  renderPanel();

  expect(await screen.findByText("reviewer-weak-triage")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "MCP (Connectors)" }));

  expect(await screen.findByText("filesystem")).toBeInTheDocument();
  expect(screen.getByText(/server-filesystem/)).toBeInTheDocument();
});

test("surfaces needs-authorization state when a remote server requires auth", async () => {
  const user = userEvent.setup();
  vi.mocked(testMcpServer).mockResolvedValueOnce({
    status: "needs-authorization",
    tools: [],
    error: "This remote MCP server requires authorization.",
  });
  renderPanel();

  await user.click(screen.getByRole("button", { name: "MCP (Connectors)" }));
  await screen.findByText("filesystem");
  await user.click(screen.getByRole("button", { name: "Test" }));

  expect(await screen.findByText(/Needs authorization/)).toBeInTheDocument();
});
