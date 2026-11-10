"""Tests for grounded prompt construction and Bedrock generation."""

import unittest

from shared import rag


def chunks():
    return [
        {
            "documentId": "123e4567-e89b-42d3-a456-426614174000",
            "chunkId": "123e4567-e89b-42d3-a456-426614174000#chunk-00001",
            "pageNumber": 2,
            "text": "Inheritance lets a class reuse behavior.",
            "score": 0.9,
        }
    ]


class FakeBedrock:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "output": {
                "message": {
                    "content": [{"text": "Inheritance supports reuse. [Source 1]"}]
                }
            },
            "usage": {"inputTokens": 100, "outputTokens": 12},
        }

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class RagTests(unittest.TestCase):
    def test_prompt_separates_sources_and_question(self):
        prompt = rag.build_grounded_prompt("What is inheritance?", chunks())

        self.assertIn("<sources>", prompt)
        self.assertIn("[Source 1", prompt)
        self.assertIn("page=2", prompt)
        self.assertIn("<question>\nWhat is inheritance?", prompt)

    def test_context_limit_truncates_source_text(self):
        long_chunks = chunks()
        long_chunks[0]["text"] = "A" * 500
        context = rag.build_context(long_chunks, max_characters=160)

        self.assertEqual(len(context), 160)
        self.assertTrue(context.startswith("[Source 1"))

    def test_generation_uses_system_prompt_and_low_temperature(self):
        client = FakeBedrock()

        result = rag.generate_grounded_answer(
            client,
            model_id="amazon.nova-micro-v1:0",
            question="What is inheritance?",
            chunks=chunks(),
        )

        self.assertEqual(result["answer"], "Inheritance supports reuse. [Source 1]")
        self.assertEqual(result["usage"]["outputTokens"], 12)
        call = client.calls[0]
        self.assertEqual(call["modelId"], "amazon.nova-micro-v1:0")
        self.assertIn("untrusted data", call["system"][0]["text"])
        self.assertEqual(call["inferenceConfig"]["temperature"], 0.1)

    def test_generation_rejects_invalid_bedrock_response(self):
        with self.assertRaisesRegex(RuntimeError, "invalid generation response"):
            rag.generate_grounded_answer(
                FakeBedrock({"output": {"message": {"content": []}}}),
                model_id="model",
                question="Question",
                chunks=chunks(),
            )


if __name__ == "__main__":
    unittest.main()
