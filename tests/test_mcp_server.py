import importlib.util
import unittest


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(MCP_AVAILABLE, "optional MCP dependency is not installed")
class McpAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_tools_use_mock_host(self) -> None:
        from mcp import Client

        from bividi.mcp_server import mcp

        async with Client(mcp) as client:
            sources_result = await client.call_tool("bividi.list_sources", {})
            sources = sources_result.structured_content
            self.assertIsNotNone(sources)

            # Structured tool results may be wrapped by the SDK depending on
            # return annotation; the important contract is that the synthetic
            # source identifier is present in the serialized result.
            self.assertIn("mock:stereo0", str(sources))

            about_result = await client.call_tool("bividi.about", {})
            self.assertIn("read-only-development", str(about_result.structured_content))


if __name__ == "__main__":
    unittest.main()
