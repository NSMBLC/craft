from craft import memory as mem
from craft.paths import Programme
from craft.util import append_jsonl


def test_tokenize():
    toks = mem.tokenize("Does Method A's advantage over the baseline hold on larger inputs?")
    assert "method" in toks and "advantage" in toks and "the" not in toks


def test_recall_hits(tmp_path):
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path)
    mem.ensure_memory_files(prog)
    append_jsonl(prog.memory_file("refuted"), {"id": "R-0001", "claim": "method A's advantage over baseline B holds on larger inputs",
                                               "investigation": "inv-000", "closed": "2026-01-01T00:00:00+00:00", "keywords": []})
    append_jsonl(prog.memory_file("finding"), {"id": "F-0001", "claim": "cosine warmup reduces variance in small models",
                                               "investigation": "inv-000", "closed": "2026-01-01T00:00:00+00:00", "keywords": []})
    mem.build_index(prog)
    hits = mem.recall(prog, "I keep wondering if method A's advantage holds on larger inputs")
    assert [h.id for h in hits] == ["R-0001"]
    assert mem.recall(prog, "unrelated topic about coffee") == []


def test_recall_rebuilds_stale_index(tmp_path):
    import os, time
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path)
    mem.ensure_memory_files(prog)
    mem.build_index(prog)
    assert mem.recall(prog, "method A advantage baseline large inputs") == []
    append_jsonl(prog.memory_file("refuted"), {"id": "R-0001", "claim": "method A advantage over baseline on large inputs",
                                               "investigation": "inv-000", "closed": "2026-01-01T00:00:00+00:00"})
    future = time.time() + 5
    os.utime(prog.memory_file("refuted"), (future, future))
    assert [h.id for h in mem.recall(prog, "method A advantage baseline large inputs")] == ["R-0001"]
