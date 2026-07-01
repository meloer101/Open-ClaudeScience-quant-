import json
from types import SimpleNamespace


class FakeLLMClient:
    """Scripted stand-in for LLMClient so tests don't need network/API keys.

    `script` is a list of turns, each either:
      ("tools", [(tool_name, args_dict), ...])  - assistant makes tool calls
      ("text", content)                          - assistant gives a final answer
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append((messages, tools))
        kind, payload = self.script.pop(0)
        if kind == "text":
            message = SimpleNamespace(role="assistant", content=payload, tool_calls=None)
        else:
            tool_calls = [
                SimpleNamespace(
                    id=f"call_{i}",
                    function=SimpleNamespace(name=name, arguments=json.dumps(args)),
                )
                for i, (name, args) in enumerate(payload)
            ]
            message = SimpleNamespace(role="assistant", content=None, tool_calls=tool_calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
