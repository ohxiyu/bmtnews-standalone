import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("governance", ROOT / "scripts/check_governance.py")
governance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(governance)


@pytest.fixture
def tree(tmp_path):
    paths = [*governance.OWNED_DOCS, "VERSION", "pyproject.toml", "uv.lock",
             "ops/daily-dispatcher/package.json", "ops/daily-dispatcher/package-lock.json"]
    paths += [str(p.relative_to(ROOT)) for p in (ROOT / "project-docs").rglob("*") if p.is_file()]
    paths += ["docs/openapi.json"]
    for relative in set(paths):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def test_repository_governance():
    assert governance.check() == []


def test_versions_are_component_scoped(tree):
    assert governance.check(tree) == []
    (tree / "VERSION").write_text("9.0.0\n")
    assert any("version" in e for e in governance.check(tree))


def test_worker_lock_mismatch(tree):
    path = tree / "ops/daily-dispatcher/package-lock.json"
    payload = json.loads(path.read_text())
    payload["packages"][""]["version"] = "2.0.0"
    path.write_text(json.dumps(payload))
    assert any("dispatcher" in e for e in governance.check(tree))


@pytest.mark.parametrize("target", ["missing.md", "../../../../outside.md"])
def test_broken_or_escaping_links(tree, target):
    (tree / "agent.md").write_text(f"[rules](AGENTS.md) [bad]({target})")
    assert any("broken local link" in e for e in governance.check(tree))


def test_duplicate_pointer_rejected(tree):
    path = tree / "project-docs/handoff.md"
    path.write_text(path.read_text() + "\n<!-- execution-pointer -->\n")
    assert any("exactly one" in e for e in governance.check(tree))


def test_false_deployment_state_rejected(tree):
    path = tree / "project-docs/handoff.md"
    path.write_text(path.read_text().replace('"deployed": "not_required"', '"deployed": "complete"'))
    assert any("deployed complete requires" in e for e in governance.check(tree))


def test_application_pr_requires_handoff_and_evidence():
    assert len(governance.check_change_evidence(["src/models.py"])) == 2
    assert governance.check_change_evidence(["src/models.py", "project-docs/handoff.md",
                                             "project-docs/releases/change.md"]) == []
    assert governance.check_change_evidence(["README.md"]) == []


def test_git_refs_are_not_shell_input(tmp_path):
    with pytest.raises(ValueError):
        governance.changed_paths(tmp_path, "main;echo unsafe", "a" * 40)


def test_deleted_release_is_not_delivery_evidence(tmp_path):
    errors = governance.check_change_evidence(
        ["src/models.py", "project-docs/handoff.md", "project-docs/releases/deleted.md"], tmp_path
    )
    assert errors == ["application PR must include a release/verification record"]


def test_deployed_claim_requires_structured_evidence(tree):
    path = tree / "project-docs/handoff.md"
    text = path.read_text()
    import re
    match = re.search(r"```json\s*(.*?)\s*```", text, re.S)
    pointer = json.loads(match.group(1))
    pointer["states"] = {name: "complete" for name in governance.STATES}
    path.write_text(text[:match.start(1)] + json.dumps(pointer) + text[match.end(1):])
    assert any("deployment evidence missing Source commit" in e for e in governance.check(tree))
