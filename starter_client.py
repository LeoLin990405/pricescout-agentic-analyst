"""AI-powered MCP client for the PriceScout agentic analyst project."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, TypedDict

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class ToolDefinition(TypedDict):
    name: str
    description: str | None
    input_schema: dict[str, Any]


class Configuration:
    """Load and validate MCP server configuration."""

    @staticmethod
    def load_config(file_path: str | Path) -> dict[str, Any]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "mcpServers" not in config:
                raise ValueError("Configuration must contain an mcpServers object")
            return config
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Config file not found: {file_path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Config file is not valid JSON: {file_path}") from exc


@dataclass
class Server:
    """Lifecycle wrapper for one stdio MCP server."""

    name: str
    config: dict[str, Any]

    def __post_init__(self) -> None:
        self.session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    async def initialize(self) -> None:
        command = self.config["command"]
        server_params = StdioServerParameters(
            command=command,
            args=self.config["args"],
            env={**os.environ, **self.config["env"]} if self.config.get("env") else None,
        )
        read_stream, write_stream = await self._exit_stack.enter_async_context(stdio_client(server_params))
        self.session = await self._exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        logging.info("Connected to MCP server: %s", self.name)

    async def list_tools(self) -> list[ToolDefinition]:
        if not self.session:
            raise RuntimeError(f"Server {self.name} is not initialized")
        tools_response = await self.session.list_tools()
        tools: list[ToolDefinition] = []
        for tool in tools_response.tools:
            tool_def: ToolDefinition = {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            tools.append(tool_def)
        return tools

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self.session:
            raise RuntimeError(f"Server {self.name} is not initialized")

        max_attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                logging.info("Executing %s on %s (attempt %s/%s)...", tool_name, self.name, attempt, max_attempts)
                result = await self.session.call_tool(
                    name=tool_name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=60),
                )
                return result
            except Exception as exc:  # pragma: no cover - defensive for external servers
                last_error = exc
                logging.warning("Tool call failed: %s", exc)
                await asyncio.sleep(0.5 * attempt)
        raise RuntimeError(f"Tool {tool_name} failed after {max_attempts} attempts") from last_error

    async def cleanup(self) -> None:
        await self._exit_stack.aclose()


class DataExtractor:
    """Persist structured model pricing plans through the SQLite MCP server."""

    def __init__(self, sqlite_server: Server) -> None:
        self.sqlite_server = sqlite_server

    async def ensure_schema(self) -> None:
        await self.sqlite_server.execute_tool(
            "write_query",
            {
                "query": """
                CREATE TABLE IF NOT EXISTS pricing_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    plan_name TEXT NOT NULL,
                    input_tokens REAL DEFAULT 0,
                    output_tokens REAL DEFAULT 0,
                    currency TEXT DEFAULT 'USD',
                    billing_period TEXT DEFAULT 'unknown',
                    features TEXT DEFAULT '[]',
                    limitations TEXT DEFAULT '',
                    source_query TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            },
        )

    async def extract_and_store_data(self, pricing_data: dict[str, Any], user_query: str) -> None:
        await self.ensure_schema()
        for plan in pricing_data.get("plans", []):
            await self.sqlite_server.execute_tool(
                "write_query",
                {
                    "query": f"""
                    INSERT INTO pricing_plans (company_name, plan_name, input_tokens, output_tokens, currency, billing_period, features, limitations, source_query)
                    VALUES (
                        '{pricing_data.get("company_name", "Unknown")}',
                        '{plan.get("plan_name", "Unknown Plan")}',
                        '{plan.get("input_tokens", 0)}',
                        '{plan.get("output_tokens", 0)}',
                        '{plan.get("currency", "USD")}',
                        '{plan.get("billing_period", "unknown")}',
                        '{json.dumps(plan.get("features", []))}',
                        '{plan.get("limitations", "")}',
                        '{user_query}')
                    """
                },
            )


class ChatSession:
    """Anthropic-powered host that chooses and calls tools from connected MCP servers."""

    def __init__(self, servers: list[Server], sqlite_server: Server) -> None:
        self.servers = servers
        self.sqlite_server = sqlite_server
        self.anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.data_extractor = DataExtractor(sqlite_server)

    async def _tool_catalog(self) -> tuple[list[dict[str, Any]], dict[str, Server]]:
        catalog: list[dict[str, Any]] = []
        tool_to_server: dict[str, Server] = {}
        for server in self.servers:
            for tool in await server.list_tools():
                catalog.append(
                    {
                        "name": tool["name"],
                        "description": tool["description"] or "",
                        "input_schema": tool["input_schema"],
                    }
                )
                tool_to_server[tool["name"]] = server
        return catalog, tool_to_server

    async def process_query(self, query: str) -> str:
        tools, tool_to_server = await self._tool_catalog()
        messages: list[dict[str, Any]] = [{"role": "user", "content": query}]
        full_response = ""
        process_query = True

        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=4096,
            tools=tools,
            messages=messages,
            system=(
                "You are PriceScout, an agentic analyst. Use MCP tools to scrape provider pricing pages, "
                "extract relevant plan costs, persist structured pricing data to SQLite when pricing plans "
                "are identified, and answer in concise natural language with sources."
            ),
        )

        while process_query:
            assistant_content: list[Any] = []

            for content in response.content:
                if content.type == "text":
                    full_response += content.text + "\n"
                    assistant_content.append(content)
                    if len(response.content) == 1:
                        process_query = False

                elif content.type == "tool_use":
                    assistant_content.append(content)
                    messages.append({"role": "assistant", "content": assistant_content})

                    tool_id = content.id
                    tool_args = content.input
                    tool_name = content.name
                    server = tool_to_server.get(tool_name)
                    if not server:
                        raise RuntimeError(f"No MCP server registered for tool: {tool_name}")

                    tool_result = await server.execute_tool(tool_name, tool_args)
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(tool_result),
                                }
                            ],
                        }
                    )

                    response = self.anthropic.messages.create(
                        model="claude-3-5-sonnet-20240620",
                        max_tokens=4096,
                        tools=tools,
                        messages=messages,
                        system=(
                            "Continue the PriceScout workflow. If pricing plans were extracted, summarize "
                            "them and explain which providers are cheaper for the requested model."
                        ),
                    )

                    if len(response.content) == 1 and response.content[0].type == "text":
                        full_response += response.content[0].text + "\n"
                        process_query = False
                    break

        return full_response.strip()

    async def show_stored_data(self) -> None:
        pricing = await self.sqlite_server.execute_tool(
            "read_query",
            {
                "query": "SELECT company_name, plan_name, input_tokens, output_tokens, currency FROM pricing_plans ORDER BY created_at DESC LIMIT 5"
            },
        )

        print("\nRecently Stored Data:")
        print("=" * 50)

        print("\nPricing Plans:")
        for plan in pricing.content[0]["text"]:
            print(
                f"  - {plan['company_name']}: {plan['plan_name']} - "
                f"Input Token ${plan['input_tokens']}, Output Tokens ${plan['output_tokens']}"
            )

        print("=" * 50)


async def main() -> None:
    config = Configuration.load_config("server_config.json")
    servers = [Server(name, server_config) for name, server_config in config["mcpServers"].items()]

    try:
        for server in servers:
            await server.initialize()
        sqlite_server = next(server for server in servers if server.name == "sqlite")
        chat_session = ChatSession(servers, sqlite_server)

        print("PriceScout MCP Analyst is ready. Type 'show data' or 'quit'.")
        while True:
            query = input("\nQuery: ").strip()
            if query.lower() in {"quit", "exit"}:
                break
            if query.lower() == "show data":
                await chat_session.show_stored_data()
                continue
            response = await chat_session.process_query(query)
            print("\nResponse:")
            print(response)
    finally:
        for server in servers:
            await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

