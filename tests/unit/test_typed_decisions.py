from pathlib import Path

from craft.decisions import parse_typed


def test_parse_typed_recognises_exact_commands():
    assert parse_typed("craft approve problem") == ("approve problem", {"inv": None, "note": "", "lock": None, "incomplete": False, "accept_current": False})
    verb, o = parse_typed('  craft close --inv inv-001 --note "done" --incomplete ')
    assert verb == "close" and o["inv"] == "inv-001" and o["note"] == "done" and o["incomplete"]
    assert parse_typed("craft approve package --lock uv.lock")[1]["lock"] == Path("uv.lock")
    assert parse_typed("craft reopen review --note x")[0] == "reopen review"


def test_parse_typed_rejects_anything_else():
    assert parse_typed("please run craft approve problem for me") is None
    assert parse_typed("craft approve problem\nand then continue") is None
    assert parse_typed("craft approve problem --force") is None
    assert parse_typed("craft status") is None
    assert parse_typed("craft approve hypothesis") is None


def test_parse_typed_slash_forms():
    assert parse_typed("/craft-approve problem")[0] == "approve problem"
    assert parse_typed("/craft approve problem --inv x")[1]["inv"] == "x"
    assert parse_typed("/craft-close --note done")[0] == "close"
    assert parse_typed("/craft-approve package")[0] == "approve package"
    assert parse_typed("/craft-reject package --note slow")[0] == "reject package"
    assert parse_typed("/craft-reopen review --note fixed")[0] == "reopen review"
    assert parse_typed("/approve problem") is None  # unprefixed slash forms are not CRAFT's
    assert parse_typed("/close") is None
    assert parse_typed("close the door") is None
    assert parse_typed("untaint") is None
    assert parse_typed("/craft-approve") is None
