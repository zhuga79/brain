"""Search Brain machine index with dependency-free BM25."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path



try:
    import brain_index
except ImportError as exc:
    print(f"ERROR: cannot import brain_index: {exc}", file=sys.stderr)
    sys.exit(1)


def call_brain_vector_search(query: str, limit: int = 50) -> list:
    """Delegate to brain-vector search --json, returning results list or empty."""
    try:
        bin_dir = Path(__file__).resolve().parent
        brain_vector_bin = bin_dir / "brain-vector"
        cmd = [str(brain_vector_bin), "search", query, "-k", str(limit), "--json"]
        
        # Inherit environment (BRAIN_PATH, etc.)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("results", [])
    except Exception:
        pass
    return []


def hybrid_rerank(bm25_results: list, vector_results: list, limit: int) -> list:
    """Rerank BM25 top results using Reciprocal Rank Fusion (RRF) with vector results."""
    if not vector_results:
        return bm25_results[:limit]

    # Map path -> vector rank (0-based)
    v_ranks = {res["path"]: i for i, res in enumerate(vector_results)}
    
    # RRF Score = 1 / (k + rank)
    k = 60
    scored = []
    for i, res in enumerate(bm25_results):
        # res already has 'score' (BM25)
        bm25_rank = i
        vector_rank = v_ranks.get(res["path"], 1000) # Use a large rank if not in vector top-K
        
        rrf_score = 1.0 / (k + bm25_rank) + 1.0 / (k + vector_rank)
        res["hybrid_score"] = round(rrf_score, 6)
        scored.append(res)
    
    # Sort by hybrid score
    scored.sort(key=lambda x: x["hybrid_score"], reverse=True)
    return scored[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Brain with BM25, Vector, or Hybrid modes.")
    parser.add_argument("query")
    parser.add_argument("--brain", default=os.environ.get("BRAIN_PATH", str(Path.home() / "brain")))
    parser.add_argument("--mode", choices=["bm25", "vector", "hybrid"], default="bm25", 
                        help="Search mode: bm25 (default), vector, or hybrid.")
    parser.add_argument("--type", default="", help="Filter by page type/kind: concept, decision, raw, task, ...")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    brain = brain_index.brain_wiki.brain_path(args.brain)
    
    if args.mode == "vector":
        v_results = call_brain_vector_search(args.query, limit=args.limit)
        if args.json:
            print(json.dumps({"query": args.query, "mode": "vector", "results": v_results}, 
                             ensure_ascii=False, indent=2, sort_keys=True))
        else:
            if not v_results:
                print("No vector results found.")
            for res in v_results:
                print(f"{res['score']} {res['path']} [{res['page_type']}] {res['title']}")
                if res.get("snippet"):
                    print(f"  {res['snippet']}")
        return 0

    # For BM25 or Hybrid
    status = brain_index.index_status(brain)
    if status.get("status") == "missing":
        print("ERROR: index missing; run `brain-index rebuild` first", file=sys.stderr)
        return 1

    # In hybrid mode, we want a larger pool for reranking
    bm25_limit = 50 if args.mode == "hybrid" else args.limit
    results = brain_index.search_brain(brain, args.query, page_type=args.type, limit=bm25_limit)

    if args.mode == "hybrid":
        # Get top-50 from vector for reranking
        v_results = call_brain_vector_search(args.query, limit=50)
        results = hybrid_rerank(results, v_results, args.limit)

    if args.json:
        print(json.dumps({"query": args.query, "mode": args.mode, "results": results}, 
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if not results:
        print("No results found.")
        return 0

    for result in results:
        score_val = result.get("hybrid_score", result["score"])
        score_label = "hybrid" if "hybrid_score" in result else "bm25"
        print(f"{score_val:.4f} ({score_label}) {result['path']} [{result['page_type']}] {result['title']}")
        if result.get("snippet"):
            print(f"  {result['snippet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
