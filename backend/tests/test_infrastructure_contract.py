"""Regression checks for security-critical CloudFormation contracts."""

from pathlib import Path
import unittest


TEMPLATE = (Path(__file__).parents[2] / "infrastructure" / "foundation.yaml").read_text()


class InfrastructureContractTests(unittest.TestCase):
    def test_required_http_routes_and_exact_cors_origin_remain_declared(self):
        for route in (
            "POST /upload-url",
            "POST /ask",
            "POST /study",
            "GET /documents",
            "GET /documents/{documentId}",
        ):
            self.assertIn(f"RouteKey: {route}", TEMPLATE)
        self.assertIn("AllowOrigins:\n          - !Ref FrontendOrigin", TEMPLATE)

    def test_private_storage_and_transport_controls_remain_enabled(self):
        for control in (
            "BlockPublicAcls: true",
            "BlockPublicPolicy: true",
            "IgnorePublicAcls: true",
            "RestrictPublicBuckets: true",
            "aws:SecureTransport: false",
            "SSEAlgorithm: AES256",
        ):
            self.assertIn(control, TEMPLATE)

    def test_api_throttling_logging_and_alarms_remain_enabled(self):
        self.assertIn("ThrottlingBurstLimit: 20", TEMPLATE)
        self.assertIn("ThrottlingRateLimit: 10", TEMPLATE)
        self.assertIn("AccessLogSettings:", TEMPLATE)
        self.assertIn("ApiServerErrorAlarm:", TEMPLATE)
        self.assertIn("RagLambdaErrorAlarm:", TEMPLATE)

    def test_vector_policy_keeps_read_and_write_roles_separate(self):
        self.assertIn('"${IndexDocumentRole.Arn}"', TEMPLATE)
        self.assertIn('"${AskQuestionRole.Arn}"', TEMPLATE)
        self.assertIn('"${GenerateQuestionsRole.Arn}"', TEMPLATE)
        self.assertIn('"aoss:WriteDocument"', TEMPLATE)
        self.assertIn('"aoss:ReadDocument"', TEMPLATE)


if __name__ == "__main__":
    unittest.main()
