import asyncio

from mcp_agent.core.fastagent import FastAgent

# Create the application
fast = FastAgent("MCP agents")


# Define the agent
# @fast.agent(instruction="You are a helpful AI Agent", servers=["fetch", "filesystem"])
# @fast.agent(name="web", instruction="You are a web agent", servers=["webbrowser"])
@fast.agent(name="v2ex", instruction="You 是 一个 V2ex.com 网站的服务器机器人,", servers=["v2ex"])
async def main():
    # use the --model command line switch or agent arguments to change model
    async with fast.run() as agent:
        await agent()


if __name__ == "__main__":
    asyncio.run(main())
