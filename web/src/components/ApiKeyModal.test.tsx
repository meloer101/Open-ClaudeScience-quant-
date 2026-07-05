import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ApiKeyModal } from "./ApiKeyModal";

test("prefills the model field and submits the trimmed model and key", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  render(<ApiKeyModal currentModel="deepseek/deepseek-chat" onSubmit={onSubmit} />);

  expect(screen.getByDisplayValue("deepseek/deepseek-chat")).toBeInTheDocument();
  await user.type(screen.getByPlaceholderText("sk-..."), "  sk-test-key  ");
  await user.click(screen.getByRole("button", { name: /保存并开始使用/ }));

  expect(onSubmit).toHaveBeenCalledWith("deepseek/deepseek-chat", "sk-test-key");
});

test("shows the derived provider env var for a non-default model", async () => {
  const user = userEvent.setup();
  render(<ApiKeyModal currentModel="deepseek/deepseek-chat" onSubmit={vi.fn()} />);

  const modelInput = screen.getByLabelText("模型名称");
  await user.clear(modelInput);
  await user.type(modelInput, "moonshot/kimi-k2");

  expect(screen.getByText(/将保存为 MOONSHOT_API_KEY/)).toBeInTheDocument();
});

test("lets visitors switch to another provider entirely", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  render(<ApiKeyModal currentModel="deepseek/deepseek-chat" onSubmit={onSubmit} />);

  const modelInput = screen.getByLabelText("模型名称");
  await user.clear(modelInput);
  await user.type(modelInput, "openai/gpt-4o");
  await user.type(screen.getByPlaceholderText("sk-..."), "sk-openai-key");
  await user.click(screen.getByRole("button", { name: /保存并开始使用/ }));

  expect(onSubmit).toHaveBeenCalledWith("openai/gpt-4o", "sk-openai-key");
});

test("shows an inline error instead of submitting when the model field is blank", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  render(<ApiKeyModal currentModel="" onSubmit={onSubmit} />);

  await user.type(screen.getByPlaceholderText("sk-..."), "sk-test-key");
  await user.click(screen.getByRole("button", { name: /保存并开始使用/ }));

  expect(onSubmit).not.toHaveBeenCalled();
  expect(screen.getByText("请输入模型名称")).toBeInTheDocument();
});

test("shows an inline error instead of submitting when the key field is blank", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  render(<ApiKeyModal currentModel="deepseek/deepseek-chat" onSubmit={onSubmit} />);

  await user.click(screen.getByRole("button", { name: /保存并开始使用/ }));

  expect(onSubmit).not.toHaveBeenCalled();
  expect(screen.getByText("请输入 API key")).toBeInTheDocument();
});

test("shows an error if the submit call fails", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn().mockRejectedValue(new Error("network down"));
  render(<ApiKeyModal currentModel="deepseek/deepseek-chat" onSubmit={onSubmit} />);

  await user.type(screen.getByPlaceholderText("sk-..."), "sk-test-key");
  await user.click(screen.getByRole("button", { name: /保存并开始使用/ }));

  expect(await screen.findByText(/保存失败/)).toBeInTheDocument();
});
