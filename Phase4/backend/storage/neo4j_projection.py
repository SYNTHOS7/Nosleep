"""Optional transactionally replaced Neo4j projection of the active evidence graph.

Neon/SQLite remains authoritative. Only AegisManaged nodes are owned by this adapter.
"""
def snapshot_workspace(store, workspace):
    nodes, edges = [], []
    with store._lock:
        for kind, records in (("document", store.documents.get(workspace, {})),
                              ("chunk", store.chunks.get(workspace, {})),
                              ("entity", store.entities.get(workspace, {})),
                              ("value", store.values.get(workspace, {})),
                              ("topic", store.topics.get(workspace, {}))):
            for key, record in records.items():
                nodes.append({"id": f"{kind}:{key}", "kind": kind,
                              "name": getattr(record, "name", None) or getattr(record, "source_name", None) or key,
                              "payload": record.model_dump_json()})
        node_ids = {node["id"] for node in nodes}
        for chunk in store.chunks.get(workspace, {}).values():
            edges.append({"id": f"source:{chunk.id}", "source": f"chunk:{chunk.id}",
                          "target": f"document:{chunk.document_id}", "predicate": "FROM_DOCUMENT", "payload": "{}"})
        for relation in store.relations.get(workspace, {}).values():
            target = f"entity:{relation.target_entity_name}" if relation.target_entity_name else f"value:{relation.target_value_id}"
            edges.append({"id": relation.id, "source": f"entity:{relation.source_entity_name}",
                          "target": target, "predicate": relation.predicate,
                          "payload": relation.model_dump_json()})
        for assignment in store.topic_assignments.get(workspace, []):
            edges.append({"id": f"topic:{assignment.topic_id}:{assignment.chunk_id}",
                          "source": f"chunk:{assignment.chunk_id}", "target": f"topic:{assignment.topic_id}",
                          "predicate": "IN_TOPIC", "payload": assignment.model_dump_json()})
        edges = [edge for edge in edges if edge["source"] in node_ids and edge["target"] in node_ids]
    return nodes, edges


class Neo4jProjection:
    def __init__(self, driver, database="neo4j"):
        self.driver, self.database = driver, database

    def workspaces(self):
        with self.driver.session(database=self.database) as session:
            return session.execute_read(lambda tx: [row["workspace"] for row in tx.run(
                "MATCH (n:AegisManaged) RETURN DISTINCT n.workspace_id AS workspace")])

    def replace_workspace(self, workspace, nodes, edges):
        # All document content, identifiers and predicates stay parameters, never Cypher syntax.
        def replace(tx):
            tx.run("MATCH (n:AegisManaged {workspace_id:$workspace}) DETACH DELETE n", workspace=workspace).consume()
            tx.run("""UNWIND $nodes AS row CREATE (n:AegisManaged)
                SET n.workspace_id=$workspace, n.node_id=row.id, n.kind=row.kind,
                    n.name=row.name, n.payload=row.payload""", workspace=workspace, nodes=nodes).consume()
            tx.run("""UNWIND $edges AS row
                MATCH (a:AegisManaged {workspace_id:$workspace,node_id:row.source})
                MATCH (b:AegisManaged {workspace_id:$workspace,node_id:row.target})
                CREATE (a)-[r:AEGIS_LINK]->(b)
                SET r.edge_id=row.id, r.predicate=row.predicate, r.payload=row.payload""",
                workspace=workspace, edges=edges).consume()
        with self.driver.session(database=self.database) as session:
            session.execute_write(replace)
