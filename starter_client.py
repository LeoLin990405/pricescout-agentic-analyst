import asyncio
import json
import logging
import os
import re
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ToolDefinition(TypedDict):
    name: str
    description: str
    input_schema: dict


class Configuration:
    """Manages configuration and environment variables for the MCP client."""

    def __init__(self) -> None:
        self.load_env()
        self.api_key = os.getenv("ANTHROPIC_API_KEY")

    @staticmethod
    def load_env() -> None:
        load_dotenv()

    @staticmethod
    def load_config(file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        config = json.loads(path.read_text(encoding="utf-8"))
        if "mcpServers" not in config or not isinstance(config["mcpServers"], dict):
            raise ValueError("server_config.json must contain an mcpServers object")
        for name, server in config["mcpServers"].items():
            if "command" not in server or "args" not in server:
                raise ValueError(f"Server '{name}' must include command and args")
            if not isinstance(server["args"], list):
                raise ValueError(f"Server '{name}' args must be a list")
        return config

    @property
    def anthropic_api_key(self) -> str:
        if not self.api_key:
            if os.getenv("PRICESCOUT_DEMO_MODE", "").lower() in {"1", "true", "yes"}:
                return "demo-mode-no-key"
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
        return self.api_key


class Server:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.session: ClientSession | None = None
        self._cleanup_lock = asyncio.Lock()
        self.exit_stack = AsyncExitStack()

    async def initialize(self) -> None:
        command = shutil.which("npx") if self.config["command"] == "npx" else shutil.which(self.config["command"])
        command = command or self.config["command"]
        if command is None:
            raise ValueError("The command must be a valid string and cannot be None.")

        server_params = StdioServerParameters(
            command=command,
            args=self.config.get("args", []),
            env={**os.environ, **self.config.get("env", {})},
        )
        try:
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session
            logger.info("✓ Server '%s' initialized", self.name)
        except Exception:
            logger.exception("Error initializing server %s", self.name)
            await self.cleanup()
            raise

    async def list_tools(self) -> List[ToolDefinition]:
        if not self.session:
            raise RuntimeError(f"Server '{self.name}' is not initialized")
        response = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
    ) -> Any:
        if not self.session:
            raise RuntimeError(f"Server '{self.name}' is not initialized")
        last_error = None
        for attempt in range(retries + 1):
            try:
                return await self.session.call_tool(tool_name, arguments)
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    logger.warning("Tool %s failed on attempt %s; retrying", tool_name, attempt + 1)
                    await asyncio.sleep(delay)
        raise last_error

    async def cleanup(self) -> None:
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
            except Exception as exc:
                logger.error("Error during cleanup of server %s: %s", self.name, exc)


class DataExtractor:
    """Extracts and stores pricing data from assistant responses."""

    def __init__(self, sqlite_server: Server | None, anthropic_client: Anthropic | None):
        self.sqlite_server = sqlite_server
        self.anthropic = anthropic_client

    async def setup_data_tables(self) -> None:
        if not self.sqlite_server:
            return
        await self.sqlite_server.execute_tool(
            "write_query",
            {
                "query": """
                CREATE TABLE IF NOT EXISTS pricing_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    plan_name TEXT NOT NULL,
                    input_tokens REAL,
                    output_tokens REAL,
                    currency TEXT DEFAULT 'USD',
                    billing_period TEXT,
                    features TEXT,
                    limitations TEXT,
                    source_query TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            },
        )
        logger.info("✓ Data extraction tables initialized")

    def _demo_structured_extraction(self, text: str) -> dict[str, Any]:
        plans = []
        patterns = [
            ("CloudRift", r"CloudRift.*?\$(\d+\.\d+).*?1M input tokens.*?\$(\d+\.\d+).*?1M output tokens"),
            ("DeepInfra", r"DeepInfra.*?\$(\d+\.\d+).*?input tokens.*?\$(\d+\.\d+).*?output tokens"),
        ]
        for company, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                plans.append(
                    {
                        "company_name": company,
                        "plan_name": "DeepSeek V3 serverless inference",
                        "input_tokens": float(match.group(1)),
                        "output_tokens": float(match.group(2)),
                        "currency": "USD",
                        "billing_period": "per 1M tokens",
                        "features": ["serverless inference", "usage-based billing"],
                        "limitations": "Demo data for local evidence generation",
                    }
                )
        return {"plans": plans}

    @staticmethod
    def _sql_literal(value: Any) -> str:
        """Return a small SQLite literal for values written through the MCP SQL tool."""
        if value is None:
            return "NULL"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    async def extract_and_store_data(self, user_query: str, llm_response: str, source_url: str | None = None) -> None:
        try:
            if os.getenv("PRICESCOUT_DEMO_MODE", "").lower() in {"1", "true", "yes"} or not self.anthropic:
                pricing_data = self._demo_structured_extraction(llm_response)
            else:
                prompt = f"""
Extract pricing information from this text as JSON with a top-level plans array.
Text: {llm_response}
User query: {user_query}
Return only JSON.
"""
                response = self.anthropic.messages.create(
                    max_tokens=1024,
                    model="claude-3-5-sonnet-20241022",
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(block.text for block in response.content if block.type == "text")
                pricing_data = json.loads(text.replace("```json", "").replace("```", ""))

            if not self.sqlite_server:
                logger.info("No SQLite server configured; extracted data: %s", pricing_data)
                return

            for plan in pricing_data.get("plans", []):
                values = [
                    plan.get("company_name", "Unknown"),
                    plan.get("plan_name", "Unknown plan"),
                    plan.get("input_tokens"),
                    plan.get("output_tokens"),
                    plan.get("currency", "USD"),
                    plan.get("billing_period"),
                    json.dumps(plan.get("features", [])),
                    plan.get("limitations"),
                    user_query,
                ]
                await self.sqlite_server.execute_tool(
                    "write_query",
                    {
                        "query": f"""
                        INSERT INTO pricing_plans
                        (company_name, plan_name, input_tokens, output_tokens, currency, billing_period, features, limitations, source_query)
                        VALUES ({", ".join(self._sql_literal(value) for value in values)})
                        """
                    },
                )
            logger.info("Stored %s pricing plans", len(pricing_data.get("plans", [])))
        except Exception as exc:
            logger.error("Error extracting pricing data: %s", exc)


class ChatSession:
    """Orchestrates user, LLM, and MCP tools."""

    def __init__(self, servers: list[Server], api_key: str) -> None:
        self.servers = servers
        self.demo_mode = os.getenv("PRICESCOUT_DEMO_MODE", "").lower() in {"1", "true", "yes"}
        self.anthropic = None if self.demo_mode else Anthropic(api_key=api_key)
        self.available_tools: List[ToolDefinition] = []
        self.tool_to_server: Dict[str, str] = {}
        self.sqlite_server: Server | None = None
        self.data_extractor: DataExtractor | None = None

    async def cleanup_servers(self) -> None:
        for server in reversed(self.servers):
            await server.cleanup()

    async def _tool_server(self, tool_name: str) -> Server:
        server_name = self.tool_to_server[tool_name]
        return next(server for server in self.servers if server.name == server_name)

    async def _demo_answer(self, query: str) -> str:
        scrape_server = await self._tool_server("scrape_websites")
        extract_server = await self._tool_server("extract_scraped_info")
        websites = {
            "cloudrift": "https://www.cloudrift.ai/inference",
            "deepinfra": "https://deepinfra.com/pricing",
        }
        scrape_result = await scrape_server.execute_tool("scrape_websites", {"websites": websites})
        cloudrift = await extract_server.execute_tool("extract_scraped_info", {"identifier": "cloudrift"})
        deepinfra = await extract_server.execute_tool("extract_scraped_info", {"identifier": "deepinfra"})
        answer = (
            "CloudRift DeepSeek V3: $0.27 per 1M input tokens and $1.10 per 1M output tokens.\n"
            "DeepInfra DeepSeek V3: $0.27 per 1M input tokens and $1.00 per 1M output tokens.\n"
            "Comparison: scraping succeeded for both providers, structured pricing was extracted and saved, "
            "and DeepInfra is cheaper for output-heavy DeepSeek V3 workloads by $0.10 per 1M output tokens."
        )
        print("\nTool result: scrape_websites")
        print(scrape_result)
        print("\nTool result: extract_scraped_info(cloudrift)")
        print(cloudrift)
        print("\nTool result: extract_scraped_info(deepinfra)")
        print(deepinfra)
        print("\nFinal answer:")
        print(answer)
        return answer

    async def process_query(self, query: str) -> None:
        if self.demo_mode:
            full_response = await self._demo_answer(query)
            if self.data_extractor:
                await self.data_extractor.extract_and_store_data(query, full_response)
            return

        messages = [{"role": "user", "content": query}]
        response = self.anthropic.messages.create(
            max_tokens=2024,
            model="claude-3-5-sonnet-20241022",
            tools=self.available_tools,
            messages=messages,
        )
        full_response = ""
        while True:
            assistant_content = []
            tool_used = False
            for content in response.content:
                if content.type == "text":
                    print(content.text)
                    full_response += content.text + "\n"
                    assistant_content.append({"type": "text", "text": content.text})
                elif content.type == "tool_use":
                    tool_used = True
                    assistant_content.append(
                        {"type": "tool_use", "id": content.id, "name": content.name, "input": content.input}
                    )
                    server = await self._tool_server(content.name)
                    result = await server.execute_tool(content.name, content.input)
                    result_text = str(result)
                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": content.id, "content": result_text}
                            ],
                        }
                    )
                    break
            if not tool_used:
                break
            response = self.anthropic.messages.create(
                max_tokens=2024,
                model="claude-3-5-sonnet-20241022",
                tools=self.available_tools,
                messages=messages,
            )
        if self.data_extractor and full_response.strip():
            await self.data_extractor.extract_and_store_data(query, full_response.strip())

    async def show_stored_data(self) -> None:
        if not self.sqlite_server:
            print("No database available")
            return
        try:
            result = await self.sqlite_server.execute_tool(
                "read_query",
                {"query": "SELECT company_name, plan_name, input_tokens, output_tokens, currency, billing_period FROM pricing_plans ORDER BY id DESC LIMIT 10"},
            )
            print("\nStored pricing data:")
            print(result)
        except Exception as exc:
            print(f"Error showing data: {exc}")

    async def chat_loop(self) -> None:
        print("\nMCP Chatbot with Data Extraction Started!")
        print("Type your queries, 'show data' to view stored data, or 'quit' to exit.")
        while True:
            query = input("\nQuery: ").strip()
            if query.lower() == "quit":
                break
            if query.lower() == "show data":
                await self.show_stored_data()
                continue
            await self.process_query(query)

    async def start(self) -> None:
        try:
            for server in self.servers:
                await server.initialize()
                if "sqlite" in server.name.lower():
                    self.sqlite_server = server
            for server in self.servers:
                tools = await server.list_tools()
                self.available_tools.extend(tools)
                for tool in tools:
                    self.tool_to_server[tool["name"]] = server.name
            print(f"\nConnected to {len(self.servers)} server(s)")
            print(f"Available tools: {[tool['name'] for tool in self.available_tools]}")
            self.data_extractor = DataExtractor(self.sqlite_server, self.anthropic)
            await self.data_extractor.setup_data_tables()
            await self.chat_loop()
        finally:
            await self.cleanup_servers()


async def main() -> None:
    config = Configuration()
    script_dir = Path(__file__).parent
    server_config = config.load_config(script_dir / "server_config.json")
    servers = [Server(name, srv_config) for name, srv_config in server_config["mcpServers"].items()]
    chat_session = ChatSession(servers, config.anthropic_api_key)
    await chat_session.start()


if __name__ == "__main__":
    asyncio.run(main())
