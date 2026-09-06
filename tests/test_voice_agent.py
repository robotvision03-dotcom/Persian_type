import unittest
from unittest.mock import patch

from app import voice_agent
from app.dialogue import DialogueManager

class VoiceAgentTests(unittest.TestCase):
    def test_status_without_key(self):
        payload = voice_agent.status_payload()
        self.assertIn("enabled", payload)
        self.assertFalse(payload["enabled"])

    def test_rejects_placeholder_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-..."}, clear=False):
            self.assertEqual(voice_agent.api_key(), "")
            self.assertFalse(voice_agent.is_configured())
            self.assertIn("نامعتبر", voice_agent.status_payload()["message"])

    def test_process_utterance_tool(self):
        dialogue = DialogueManager()
        dialogue.start("voice-test-1")
        result = voice_agent.run_tool(
            "process_customer_utterance",
            {"text": "پژو"},
            session_id="voice-test-1",
            dialogue=dialogue,
        )
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("reply") or result.get("speak"))

if __name__ == "__main__":
    unittest.main()
