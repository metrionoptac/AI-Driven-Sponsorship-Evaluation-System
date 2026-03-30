"""
Copilot Agent -- Claude Sonnet with tool-use for conversational DB queries.
The copilot can search requests, check budgets, compare sponsorships, and more.
"""

import json
import logging
from anthropic import AsyncAnthropic

from app.copilot.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_FALLBACK = """You are the Sponsorship Copilot for a regional company.
You help employees manage and analyze sponsorship requests.
You have access to tools that query the sponsorship database. Use them to answer questions accurately.

When answering:
- Be concise and direct
- Use actual numbers from the database
- Format amounts as EUR with thousands separators
- If asked about a specific request, use get_request_detail
- If asked about trends or comparisons, use run_analytics_query
- If you don't have enough info, ask clarifying questions
- Respond in the same language the user writes in (German or English)
"""


async def build_system_prompt(db) -> str:
    """Build a dynamic system prompt from the active strategy in DB."""
    try:
        async with db.acquire() as conn:
            strategy = await conn.fetchrow(
                "SELECT * FROM sponsorship_strategy WHERE active = TRUE ORDER BY created_at DESC LIMIT 1"
            )
        if not strategy:
            return SYSTEM_PROMPT_FALLBACK

        import json as _json
        client_name = strategy.get("client_name", "Unknown Company")
        total_budget = float(strategy.get("total_budget", 0))
        remaining_budget = float(strategy.get("remaining_budget", 0))
        max_single = float(strategy.get("max_single_amount", 10000))
        min_single = float(strategy.get("min_single_amount", 100))

        focus_raw = strategy.get("focus_areas", "[]")
        if isinstance(focus_raw, str):
            focus_raw = _json.loads(focus_raw)
        focus_labels = [f.get("label", f.get("category", "")) for f in focus_raw] if isinstance(focus_raw, list) else []

        region_raw = strategy.get("region_priorities", "[]")
        if isinstance(region_raw, str):
            region_raw = _json.loads(region_raw)
        region_info = []
        if isinstance(region_raw, list):
            for r in region_raw:
                region_info.append(f"{r.get('region', '')} ({r.get('priority', '')})")

        blocked = list(strategy.get("blocked_categories", []))
        pipeline_mode = "COPILOT"  # default

        return f"""You are the Sponsorship Copilot for {client_name}.
You help employees manage and analyze sponsorship requests.
You have access to tools that query the sponsorship database. Use them to answer questions accurately.

Current configuration:
- Client: {client_name}
- Annual budget: {total_budget:,.0f} EUR
- Remaining budget: {remaining_budget:,.0f} EUR ({remaining_budget/total_budget*100:.0f}% left)
- Amount range per request: {min_single:,.0f} - {max_single:,.0f} EUR
- Focus areas: {', '.join(focus_labels) if focus_labels else 'Not configured'}
- Regions: {', '.join(region_info) if region_info else 'Not configured'}
- Blocked org types: {', '.join(blocked) if blocked else 'None'}
- Pipeline mode: {pipeline_mode}

When answering:
- Be concise and direct
- Use actual numbers from the database, not the budget figures above (those may be outdated)
- Format amounts as EUR with thousands separators
- If asked about a specific request, use get_request_detail
- If asked about trends or comparisons, use run_analytics_query
- If asked to approve/reject/defer, use the action tools and always confirm before executing
- If you don't have enough info, ask clarifying questions
- Respond in the same language the user writes in (German or English)
"""
    except Exception as e:
        logger.warning("Failed to build dynamic system prompt: %s", e)
        return SYSTEM_PROMPT_FALLBACK


class CopilotAgent:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.client = AsyncAnthropic(api_key=config.llm.anthropic_api_key)
        self.model = config.llm.sonnet_model

    async def get_proactive_suggestion(self, page: str, context: dict | None = None) -> str | None:
        """
        D7: Generate context-aware proactive suggestion on page load.
        Returns a suggestion string or None if nothing relevant.
        """
        try:
            async with self.db.acquire() as conn:
                pending_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM requests WHERE state = 'human_review'"
                )
                strategy = await conn.fetchrow(
                    "SELECT total_budget, remaining_budget FROM sponsorship_strategy WHERE active = TRUE LIMIT 1"
                )

                # Check oldest pending
                oldest = await conn.fetchrow(
                    "SELECT created_at FROM requests WHERE state = 'human_review' ORDER BY created_at ASC LIMIT 1"
                )

            suggestions = []

            # Pending review queue
            if pending_count and pending_count >= 3:
                age_text = ""
                if oldest:
                    from datetime import datetime, timezone
                    age = datetime.now(timezone.utc) - oldest["created_at"]
                    age_text = f" Der aelteste Antrag wartet seit {age.days} Tagen."
                suggestions.append(
                    f"Sie haben {pending_count} Antraege zur Pruefung.{age_text} "
                    f"Soll ich eine Zusammenfassung zeigen?"
                )

            # Budget warning
            if strategy:
                remaining = float(strategy["remaining_budget"])
                total = float(strategy["total_budget"])
                pct = (remaining / total * 100) if total > 0 else 0
                if pct < 20:
                    suggestions.append(
                        f"Budget-Warnung: Nur noch {pct:.0f}% des Jahresbudgets "
                        f"({remaining:,.0f} EUR) verfuegbar."
                    )

            # Context-specific: viewing a request detail
            if context and context.get("request_id"):
                rid = context["request_id"]
                async with self.db.acquire() as conn:
                    ext = await conn.fetchrow(
                        "SELECT extracted_data->>'organization_name' as org FROM extraction_results WHERE request_id = $1::uuid LIMIT 1",
                        rid,
                    )
                    if ext and ext["org"]:
                        hist = await conn.fetchval(
                            "SELECT COUNT(*) FROM historical_sponsorships WHERE organization_name ILIKE $1",
                            f"%{ext['org']}%",
                        )
                        if hist and hist > 0:
                            suggestions.append(
                                f"'{ext['org']}' hat bereits {hist} fruehere Antraege. "
                                f"Soll ich die Historie anzeigen?"
                            )

            return suggestions[0] if suggestions else None

        except Exception as e:
            logger.warning("Proactive suggestion failed: %s", e)
            return None

    async def chat(self, messages: list[dict], context: dict | None = None,
                   on_tool_start=None, on_tool_result=None) -> str:
        """
        Process a chat message with tool-use.
        messages: list of {"role": "user"|"assistant", "content": "..."}
        context: optional dict with current page context (e.g., current request_id)
        on_tool_start: optional async callback(tool_name) called when a tool is invoked
        on_tool_result: optional async callback(tool_name) called when a tool returns
        """
        system = await build_system_prompt(self.db)
        if context and context.get("request_id"):
            system += f"\n\nThe user is currently viewing request: {context['request_id']}"
        if context and context.get("page"):
            system += f"\nThey are on the '{context['page']}' page of the dashboard."

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Handle tool-use loop (max 5 iterations)
            iterations = 0
            while response.stop_reason == "tool_use" and iterations < 5:
                iterations += 1
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        logger.info("Copilot calling tool: %s(%s)", block.name, json.dumps(block.input)[:200])
                        # D9: Notify caller about tool execution
                        if on_tool_start:
                            await on_tool_start(block.name)
                        result = await execute_tool(self.db, block.name, block.input)
                        if on_tool_result:
                            await on_tool_result(block.name)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages = messages + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ]

                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    system=system,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )

            # Extract text response
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(text_parts) if text_parts else "I couldn't generate a response."

        except Exception as e:
            logger.exception("Copilot chat failed: %s", e)
            return f"Sorry, I encountered an error: {str(e)}"
