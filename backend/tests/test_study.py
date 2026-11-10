import unittest
from unittest.mock import Mock

from shared.retrieval import RetrievalValidationError
from shared.study import build_study_prompt, generate_study_material, retrieval_query, validate_study_request


class StudyTests(unittest.TestCase):
    def test_validates_and_builds_topic_query(self):
        request = validate_study_request({"mode": "questions", "topic": "mitosis", "count": 4, "questionType": "mixed"})
        self.assertIn("mitosis", retrieval_query(request))

    def test_rejects_invalid_count(self):
        with self.assertRaises(RetrievalValidationError):
            validate_study_request({"mode": "questions", "count": 0})

    def test_prompt_contains_sources_and_task(self):
        request = validate_study_request({"mode": "summary"})
        prompt = build_study_prompt(request, [{"documentId": "doc", "chunkId": "c1", "pageNumber": 2, "text": "Cells divide."}], max_characters=1000)
        self.assertIn("Cells divide", prompt)
        self.assertIn("structured summary", prompt)

    def test_generation_uses_converse(self):
        client = Mock()
        client.converse.return_value = {"output": {"message": {"content": [{"text": "A summary [Source 1]."}]}}, "usage": {"outputTokens": 6}}
        request = validate_study_request({"mode": "summary"})
        result = generate_study_material(client, model_id="model", request=request, chunks=[{"documentId": "doc", "chunkId": "c1", "pageNumber": 1, "text": "Material"}])
        self.assertEqual(result["title"], "Course summary")
        self.assertIn("Source 1", result["content"])


if __name__ == "__main__":
    unittest.main()
