import json
from typing import Any

from quantbench.agent.run_context import _RunContext
from quantbench.artifact.store import text_sha256
from quantbench.review import CriticReport, run_critic


def _run_critic_for_context(ctx: _RunContext, run, critic_llm, summary: str, context: dict[str, Any]) -> CriticReport | None:
    if ctx.review_report is None or not ctx.signal_code:
        return None
    critic_report = run_critic(
        critic_llm,
        code=ctx.signal_code,
        review_report=ctx.review_report,
        metrics=ctx.last_metrics or {},
        summary=summary,
        context=context,
        usage_sink=ctx.llm_usage,
    )
    ctx.critic_report = critic_report
    ctx.delegations.append(
        {
            "name": "critic",
            "turns_used": 1,
            "output_hash": f"sha256:{text_sha256(json.dumps(critic_report.to_dict(), sort_keys=True, default=str))}",
        }
    )
    run.save_json("critic_report.json", critic_report.to_dict())
    if critic_report.status == "ok" and critic_report.agrees_with_deterministic_verdict is False:
        deterministic = ctx.review_report.verdict
        ctx.warnings.append(
            "Critic Agent 独立复核认为应为 "
            f"{critic_report.verdict}，与确定性 verdict（{deterministic}）不一致：{critic_report.critique[:200]}"
        )
    return critic_report


def _critic_context(ctx: _RunContext) -> dict[str, Any]:
    context: dict[str, Any] = {"cost_bps": ctx.cost_bps}
    if ctx.execution is not None:
        context["execution"] = ctx.execution.to_dict()
    if ctx.universe is not None:
        context.update(
            {
                "asset_class": ctx.universe.asset_class,
                "universe": ctx.universe.name,
                "symbols": len(ctx.universe.symbols),
            }
        )
    if ctx.fetch_params:
        context.update(ctx.fetch_params)
        context["asset_class"] = "crypto" if "/" in ctx.fetch_params.get("symbol", "") else "equity"
    return context
