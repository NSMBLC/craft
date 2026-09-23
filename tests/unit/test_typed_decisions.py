from pathlib import Path

from craft.decisions import parse_typed


def test_parse_typed_decisions():
    verb, o = parse_typed("/craft-approve")
    assert verb == "approve" and o["subject"] is None
    assert parse_typed("/craft-approve problem")[1]["subject"] == "problem"
    assert parse_typed("/craft-approve package --lock uv.lock")[1]["lock"] == Path("uv.lock")
    assert parse_typed("craft approve --inv x")[1]["inv"] == "x"
    assert parse_typed("/craft approve")[0] == "approve"
    verb, o = parse_typed('  /craft-close --inv inv-001 --note "done" --incomplete ')
    assert verb == "close" and o["inv"] == "inv-001" and o["note"] == "done" and o["incomplete"]
    assert parse_typed("/craft-reject --note slow")[0] == "reject"
    assert parse_typed("/craft-reopen review --note fixed")[1]["subject"] == "review"
    assert parse_typed("/craft-resolve --note x --accept-current")[1]["accept_current"]


def test_parse_typed_queries():
    assert parse_typed("/craft-status")[0] == "status"
    assert parse_typed("/craft-help")[0] == "help"
    assert parse_typed("/craft-decisions --inv a")[1]["inv"] == "a"
    assert parse_typed("/craft-explain F-0001")[1]["arg"] == "F-0001"
    assert parse_typed("/craft-explain") is None


def test_parse_typed_rejects_anything_else():
    assert parse_typed("please run craft approve for me") is None
    assert parse_typed("/craft-approve\nand then continue") is None
    assert parse_typed("/craft-approve --force") is None
    assert parse_typed("/craft-approve hypothesis") is None
    assert parse_typed("/craft-reopen") is None
    assert parse_typed("/approve") is None
    assert parse_typed("/close") is None
    assert parse_typed("close the door") is None
    assert parse_typed("untaint") is None
