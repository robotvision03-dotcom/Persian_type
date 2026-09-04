import unittest
from unittest.mock import patch

from app.ollama import build_eval_prompt, persian_ratio, resolve_test_models, test_models


class OllamaHelperTests(unittest.TestCase):
    def test_persian_ratio(self):
        self.assertGreater(persian_ratio("این متن فارسی است"), 0.8)
        self.assertLess(persian_ratio("this is english"), 0.2)

    def test_prompt_contains_transcript(self):
        prompt = build_eval_prompt("سلام خوبی")
        self.assertIn("سلام خوبی", prompt)
        self.assertIn("فارسی", prompt)

    def test_resolve_prefers_installed_names(self):
        available = ["llama3.2:3b", "unused:latest"]
        self.assertEqual(resolve_test_models(available), ["llama3.2:3b"])

    def test_models_compare_speed_and_persian(self):
        def fake_list(_host=None):
            return ["llama3.2:3b"]

        replies = [
            {
                "model": "llama3.2:3b",
                "text": "سلام، خوبی؟",
                "ms": 80,
                "eval_count": 12,
                "tokens_per_sec": 40.0,
                "persian_ratio": 1.0,
            },
        ]

        def fake_generate(model, prompt, host=None):
            return replies.pop(0)

        with patch("app.ollama.list_ollama_models", fake_list), patch(
            "app.ollama.generate", fake_generate
        ):
            payload = test_models("سلام")
        self.assertEqual(payload["fastest"], "llama3.2:3b")
        self.assertEqual(payload["most_persian"], "llama3.2:3b")
        self.assertEqual(len(payload["results"]), 1)


if __name__ == "__main__":
    unittest.main()
