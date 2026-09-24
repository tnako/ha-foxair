"""Release pipeline guards (2026-09-25: v0.7.8 tagged but never released —
a tag pushed with GITHUB_TOKEN does not trigger the tag-based Release workflow).

The release must be created in the same workflow run as the tag, on every push
to main, idempotently, and fail loudly when the changelog section is missing.
"""
import importlib.util
import pathlib

import pytest

R = pathlib.Path(__file__).resolve().parent.parent
WF = R / ".github/workflows"
_spec = importlib.util.spec_from_file_location("release_notes", R / "tools/release_notes.py")
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)


def test_current_version_has_release_notes():
    ver = (R / "VERSION").read_text().strip()
    body = rn.section(ver, (R / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert body.startswith(f"## {ver}") and "\n- " in body


def test_section_stops_at_next_version_and_needs_exact_match():
    text = "## 1.2.10 - d\n- ten\n\n## 1.2.1 - d\n- one\n\n## 1.2.0 - d\n- zero\n"
    assert rn.section("1.2.1", text) == "## 1.2.1 - d\n- one\n"
    assert "ten" in rn.section("1.2.10", text) and "one" not in rn.section("1.2.10", text)
    with pytest.raises(LookupError):
        rn.section("1.2", text)


def test_release_runs_on_main_push_and_creates_release_in_same_run():
    wf = (WF / "release.yml").read_text()
    on = wf[wf.index("\non:"):wf.index("\npermissions:")]
    assert "branches: [main]" in on and "workflow_dispatch" in on
    assert "contents: write" in wf
    assert "git push origin \"$TAG\"" in wf and "gh release create" in wf
    assert wf.index("git push origin") < wf.index("gh release create"), "tag and release must be one run"
    assert "gh release edit" in wf, "re-runs must heal an existing tag/release"
    assert "tools/release_notes.py" in wf


def test_no_workflow_relies_on_a_bot_pushed_tag_to_release():
    for f in WF.glob("*.yml"):
        wf = f.read_text()
        if "git push origin" in wf and "tag" in wf:
            assert "gh release create" in wf, f"{f.name} pushes a tag but does not release (GITHUB_TOKEN tags trigger nothing)"
