from __future__ import annotations

import unittest

from src.schemas import AgentProposal, EvidencePack, ReviewerProposal
from src.structured import strict_schema


def walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


class StrictSchemaTests(unittest.TestCase):
    def check(self, model):
        schema = strict_schema(model)
        for path, node in walk(schema):
            self.assertNotIn("default", node, path)
            if node.get("type") == "object" or "properties" in node:
                self.assertIs(node.get("additionalProperties"), False, path)
                self.assertEqual(sorted(node["required"]), sorted(node["properties"]), path)
        refs = [n["$ref"] for _, n in walk(schema) if "$ref" in n]
        for ref in refs:
            self.assertIn(ref.split("/")[-1], schema.get("$defs", {}))
        return schema

    def test_agent_proposal(self):
        schema = self.check(AgentProposal)
        excerpt = schema["properties"]["injection_excerpt"]
        self.assertIn({"type": "null"}, excerpt["anyOf"])
        self.assertIn("injection_excerpt", schema["required"])

    def test_evidence_pack(self):
        schema = self.check(EvidencePack)
        self.assertIn("gaps", schema["required"])
        self.assertIn("unsupported_or_unverified", schema["required"])

    def test_reviewer_proposal(self):
        schema = self.check(ReviewerProposal)
        self.assertIn("analyst_audit", schema["required"])

    def test_model_schema_not_mutated(self):
        strict_schema(AgentProposal)
        self.assertNotIn("additionalProperties", AgentProposal.model_json_schema())


if __name__ == "__main__":
    unittest.main()
