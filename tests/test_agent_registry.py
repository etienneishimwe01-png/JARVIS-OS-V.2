import unittest

from agent.registry import ConfirmationRequired, RiskLevel, discover_tools, get_tool


class AgentRegistryTests(unittest.TestCase):
    def test_discovery_contains_existing_core_tools(self):
        names = {tool.name for tool in discover_tools()}
        self.assertTrue({"file_controller", "browser_control", "open_app"}.issubset(names))

    def test_unknown_tools_are_not_available(self):
        self.assertIsNone(get_tool("made_up_tool"))

    def test_required_parameter_validation_is_structured(self):
        tool = get_tool("file_controller")
        self.assertEqual(tool.validate({}), ["action"])
        self.assertEqual(tool.validate({"action": "list"}), [])

    def test_external_actions_are_marked_for_confirmation(self):
        self.assertTrue(get_tool("send_message").needs_confirmation({"action": "send"}))
        self.assertEqual(get_tool("send_message").risk, RiskLevel.MEDIUM)

    def test_read_only_file_actions_do_not_require_confirmation(self):
        tool = get_tool("file_controller")
        self.assertFalse(tool.needs_confirmation({"action": "read"}))
        self.assertTrue(tool.needs_confirmation({"action": "write"}))

    def test_confirmation_exception_is_permission_error(self):
        self.assertTrue(issubclass(ConfirmationRequired, PermissionError))


if __name__ == "__main__":
    unittest.main()