"""Foreign-key graph + join-path search.

This runs **after** the LLM has chosen which tables to query. Its job is not to pick tables — it
is to connect the tables the LLM picked with authoritative ON clauses, and to pull in any *bridge*
tables required to make the chosen set joinable (e.g. Genre→Track→InvoiceLine: the LLM asks for
Genre and InvoiceLine, the graph supplies Track).

At thousands of tables you cannot ask a model to eyeball join paths, and a full Steiner tree is
NP-hard, so we use the standard cheap approximation: connect the anchor set via a union of
shortest paths (BFS on the undirected FK graph). Edges carry the exact ON clause from the catalog
relationships, which come straight from `PRAGMA foreign_key_list` — so the joins can't drift from
what the database enforces.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class FKGraph:
    def __init__(self, adjacency: dict[str, list[tuple[str, str]]]):
        # table -> list of (neighbor_table, exact_on_clause)
        self.adj = adjacency

    @classmethod
    def build(cls, catalog: dict[str, Any]) -> "FKGraph":
        adj: dict[str, list[tuple[str, str]]] = {t: [] for t in catalog.get("tables", {})}
        for rel in catalog.get("relationships", []):
            a = rel["from"].split(".")[0]
            b = rel["to"].split(".")[0]
            on = rel["join"]
            adj.setdefault(a, []).append((b, on))
            adj.setdefault(b, []).append((a, on))  # undirected: joins go either way
        return cls(adj)

    def _shortest_path(self, src: str, dst: str) -> list[tuple[str, str]] | None:
        """BFS edges (table, on_clause) from src to dst, or None if disconnected."""
        if src == dst:
            return []
        prev: dict[str, tuple[str, str]] = {}
        q = deque([src])
        seen = {src}
        while q:
            cur = q.popleft()
            for nbr, on in self.adj.get(cur, []):
                if nbr in seen:
                    continue
                prev[nbr] = (cur, on)
                if nbr == dst:
                    path, node = [], dst
                    while node != src:
                        p, on_c = prev[node]
                        path.append((node, on_c))
                        node = p
                    return list(reversed(path))
                seen.add(nbr)
                q.append(nbr)
        return None

    def connect(self, anchors: list[str]) -> dict[str, Any]:
        """Connect the anchor tables. Returns the full table set (anchors + bridges), the exact
        join ON clauses, and any anchors that couldn't be connected (a real signal — the question
        may span unrelated subject areas and need clarification)."""
        anchors = [a for a in dict.fromkeys(anchors) if a in self.adj]
        if not anchors:
            return {"tables": [], "join_clauses": [], "bridge_tables": [], "unconnected": []}

        included = {anchors[0]}
        join_clauses: list[str] = []
        unconnected: list[str] = []
        # Greedily attach each remaining anchor to the growing connected component.
        for target in anchors[1:]:
            best: list[tuple[str, str]] | None = None
            for node in included:
                path = self._shortest_path(node, target)
                if path is not None and (best is None or len(path) < len(best)):
                    best = path
            if best is None:
                unconnected.append(target)
                included.add(target)  # keep it so the LLM's column selection isn't dropped
                continue
            for tbl, on in best:
                included.add(tbl)
                if on not in join_clauses:
                    join_clauses.append(on)

        bridges = sorted(included - set(anchors))
        return {
            "tables": sorted(included),
            "join_clauses": join_clauses,
            "bridge_tables": bridges,
            "unconnected": unconnected,
        }
