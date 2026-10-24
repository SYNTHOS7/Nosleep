"""
Tests for contradiction and conflict detection.
Covers the three defined testable conflict conditions:
1. Opposite polarity
2. Exclusive predicate value conflicts
3. Planted catalog incompatible statement pairs
"""

import unittest

from backend.contracts.models import (
    Chunk,
    Conflict,
    Entity,
    Evidence,
    Location,
    Relation,
    Value,
)
from backend.conflicts.detector import find_conflicts


class TestConflictDetection(unittest.TestCase):
    def setUp(self):
        self.ws_id = "ws_conflict_test"
        self.chunk1 = Chunk(id="c1", workspace_id=self.ws_id, document_id="d1", revision_id="r1", index=0, text="System A connects to System B.", text_hash="h1", location=Location(start_offset=0, end_offset=30))
        self.chunk2 = Chunk(id="c2", workspace_id=self.ws_id, document_id="d2", revision_id="r2", index=0, text="System A does not connect to System B.", text_hash="h2", location=Location(start_offset=0, end_offset=38))
        self.chunk3 = Chunk(id="c3", workspace_id=self.ws_id, document_id="d3", revision_id="r3", index=0, text="API license is open source.", text_hash="h3", location=Location(start_offset=0, end_offset=27))
        self.chunk4 = Chunk(id="c4", workspace_id=self.ws_id, document_id="d4", revision_id="r4", index=0, text="API license is proprietary closed source.", text_hash="h4", location=Location(start_offset=0, end_offset=41))

    def test_condition1_opposite_polarity(self):
        # Positive relation
        rel_pos = Relation(
            id="rel_pos",
            workspace_id=self.ws_id,
            revision_id="r1",
            subject_id="ent_sys_a",
            object_entity_id="ent_sys_b",
            predicate="CONNECTS_TO",
            predicate_original="connects to",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk1.id, start=0, end=len(self.chunk1.text), quote=self.chunk1.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        # Negative relation
        rel_neg = Relation(
            id="rel_neg",
            workspace_id=self.ws_id,
            revision_id="r2",
            subject_id="ent_sys_a",
            object_entity_id="ent_sys_b",
            predicate="CONNECTS_TO",
            predicate_original="does not connect to",
            polarity="negative",
            evidence=Evidence(chunk_id=self.chunk2.id, start=0, end=len(self.chunk2.text), quote=self.chunk2.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )

        conflicts = find_conflicts([rel_pos, rel_neg])
        self.assertEqual(len(conflicts), 1)
        conf = conflicts[0]
        self.assertEqual(conf.kind, "negation")
        self.assertEqual(conf.state, "supported")
        self.assertIn(rel_pos.id, [conf.left_relation_id, conf.right_relation_id])
        self.assertIn(rel_neg.id, [conf.left_relation_id, conf.right_relation_id])
        self.assertIn(self.chunk1.id, conf.evidence_chunk_ids)
        self.assertIn(self.chunk2.id, conf.evidence_chunk_ids)

    def test_condition2_exclusive_value_conflict(self):
        val_os = Value(id="val_os", workspace_id=self.ws_id, kind="text", lexical_value="open_source", normalized_value="open_source")
        val_prop = Value(id="val_prop", workspace_id=self.ws_id, kind="text", lexical_value="proprietary", normalized_value="proprietary")
        values = {val_os.id: val_os, val_prop.id: val_prop}

        rel_a = Relation(
            id="rel_val_a",
            workspace_id=self.ws_id,
            revision_id="r3",
            subject_id="ent_api",
            object_value_id=val_os.id,
            predicate="license_type",
            predicate_original="license is",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk3.id, start=0, end=len(self.chunk3.text), quote=self.chunk3.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        rel_b = Relation(
            id="rel_val_b",
            workspace_id=self.ws_id,
            revision_id="r4",
            subject_id="ent_api",
            object_value_id=val_prop.id,
            predicate="license_type",
            predicate_original="license is",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk4.id, start=0, end=len(self.chunk4.text), quote=self.chunk4.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )

        conflicts = find_conflicts([rel_a, rel_b], values_by_id=values)
        self.assertEqual(len(conflicts), 1)
        conf = conflicts[0]
        self.assertEqual(conf.kind, "exclusive_value")
        self.assertIn("open_source", conf.explanation)
        self.assertIn("proprietary", conf.explanation)

    def test_condition3_planted_catalog_incompatible_statement(self):
        # Uses planted catalog: (storage_cluster, persistence, in_memory_only) vs (storage_cluster, persistence, disk_persisted)
        val_mem = Value(id="val_mem", workspace_id=self.ws_id, kind="text", lexical_value="in_memory_only", normalized_value="in_memory_only")
        val_disk = Value(id="val_disk", workspace_id=self.ws_id, kind="text", lexical_value="disk_persisted", normalized_value="disk_persisted")
        values = {val_mem.id: val_mem, val_disk.id: val_disk}

        rel_mem = Relation(
            id="rel_cat_mem",
            workspace_id=self.ws_id,
            revision_id="r1",
            subject_id="storage_cluster",
            object_value_id=val_mem.id,
            predicate="persistence",
            predicate_original="persists via",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk1.id, start=0, end=len(self.chunk1.text), quote=self.chunk1.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        rel_disk = Relation(
            id="rel_cat_disk",
            workspace_id=self.ws_id,
            revision_id="r2",
            subject_id="storage_cluster",
            object_value_id=val_disk.id,
            predicate="persistence",
            predicate_original="persists to",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk2.id, start=0, end=len(self.chunk2.text), quote=self.chunk2.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )

        conflicts = find_conflicts([rel_mem, rel_disk], values_by_id=values)
        self.assertEqual(len(conflicts), 1)
        conf = conflicts[0]
        self.assertEqual(conf.kind, "incompatible_statement")
        self.assertIn("fixture catalog", conf.explanation)


if __name__ == "__main__":
    unittest.main()
