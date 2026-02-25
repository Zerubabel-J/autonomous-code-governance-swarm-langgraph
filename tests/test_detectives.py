"""
Tests for repo_tools.py forensic functions.

These tests use synthetic file fixtures — no real repo cloning required.
"""

import ast
import tempfile
from pathlib import Path

import pytest

from src.tools.repo_tools import (
    _class_inherits_from,
    _has_annotated_reducers,
    check_graph_orchestration,
    check_safe_tool_engineering,
    check_state_management_rigor,
    check_structured_output_enforcement,
    extract_git_history,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic repo directory
# ---------------------------------------------------------------------------


def make_repo(files: dict[str, str]) -> Path:
    """Create a temporary directory tree from a {relative_path: content} dict."""
    tmpdir = tempfile.mkdtemp()
    root = Path(tmpdir)
    for rel_path, content in files.items():
        full_path = root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# AST helper tests
# ---------------------------------------------------------------------------


def test_class_inherits_from_basemodel():
    source = "from pydantic import BaseModel\nclass Foo(BaseModel):\n    x: int\n"
    tree = ast.parse(source)
    assert _class_inherits_from(tree, "BaseModel") is True


def test_class_inherits_from_typeddict():
    source = "from typing_extensions import TypedDict\nclass Bar(TypedDict):\n    y: str\n"
    tree = ast.parse(source)
    assert _class_inherits_from(tree, "TypedDict") is True


def test_class_does_not_inherit_from_missing_base():
    source = "class Plain:\n    pass\n"
    tree = ast.parse(source)
    assert _class_inherits_from(tree, "BaseModel") is False


def test_has_annotated_reducers_positive():
    source = "evidences: Annotated[Dict, operator.ior]\nopinions: Annotated[List, operator.add]"
    assert _has_annotated_reducers(source) is True


def test_has_annotated_reducers_negative():
    source = "evidences: Dict[str, List]\nopinions: List"
    assert _has_annotated_reducers(source) is False


# ---------------------------------------------------------------------------
# check_state_management_rigor
# ---------------------------------------------------------------------------


VALID_STATE = """
import operator
from typing import Annotated, Dict, List
from pydantic import BaseModel
from typing_extensions import TypedDict

class Evidence(BaseModel):
    goal: str
    found: bool

class AgentState(TypedDict):
    evidences: Annotated[Dict, operator.ior]
    opinions: Annotated[List, operator.add]
"""

MINIMAL_TYPEDDICT_NO_REDUCERS = """
from typing_extensions import TypedDict

class AgentState(TypedDict):
    evidences: dict
"""

PLAIN_DICT_STATE = """
state = {"evidences": {}, "opinions": []}
"""

SYNTAX_ERROR_STATE = "def broken(:\n    pass"


def test_state_check_valid_pydantic_with_reducers():
    repo = make_repo({"src/state.py": VALID_STATE})
    result = check_state_management_rigor(repo)
    assert result["found"] is True
    assert result["has_basemodel"] is True
    assert result["has_reducers"] is True
    assert result["parse_error"] is None


def test_state_check_typeddict_without_reducers():
    repo = make_repo({"src/state.py": MINIMAL_TYPEDDICT_NO_REDUCERS})
    result = check_state_management_rigor(repo)
    assert result["found"] is True
    assert result["has_typeddict"] is True
    assert result["has_reducers"] is False


def test_state_check_no_state_file():
    repo = make_repo({"src/other.py": "x = 1"})
    result = check_state_management_rigor(repo)
    assert result["found"] is False
    assert result["location"] == "N/A"


def test_state_check_syntax_error_does_not_raise():
    repo = make_repo({"src/state.py": SYNTAX_ERROR_STATE})
    result = check_state_management_rigor(repo)
    assert result["found"] is True
    assert result["parse_error"] is not None
    assert result["has_basemodel"] is False


def test_state_check_plain_dict_no_models():
    repo = make_repo({"src/state.py": PLAIN_DICT_STATE})
    result = check_state_management_rigor(repo)
    assert result["has_basemodel"] is False
    assert result["has_typeddict"] is False
    assert result["has_reducers"] is False


# ---------------------------------------------------------------------------
# check_safe_tool_engineering
# ---------------------------------------------------------------------------


SAFE_TOOLS = """
import subprocess
import tempfile

def clone_repo(url):
    tmpdir = tempfile.TemporaryDirectory()
    subprocess.run(["git", "clone", url, tmpdir.name], capture_output=True)
    return tmpdir
"""

UNSAFE_TOOLS = """
import os

def clone_repo(url):
    os.system(f"git clone {url}")
"""


def test_safe_tool_engineering_detects_tempfile_and_subprocess():
    repo = make_repo({"src/tools/repo_tools.py": SAFE_TOOLS})
    result = check_safe_tool_engineering(repo)
    assert result["found"] is True
    assert result["uses_tempfile"] is True
    assert result["uses_subprocess"] is True
    assert result["has_os_system"] is False


def test_safe_tool_engineering_detects_os_system_violation():
    repo = make_repo({"src/tools/repo_tools.py": UNSAFE_TOOLS})
    result = check_safe_tool_engineering(repo)
    assert result["has_os_system"] is True
    assert result["uses_tempfile"] is False


def test_safe_tool_engineering_no_tools_dir():
    repo = make_repo({"src/state.py": "x = 1"})
    result = check_safe_tool_engineering(repo)
    assert result["found"] is False


# ---------------------------------------------------------------------------
# check_structured_output_enforcement
# ---------------------------------------------------------------------------


JUDGES_WITH_STRUCTURED_OUTPUT = """
from langchain_google_genai import ChatGoogleGenerativeAI
from src.state import JudicialOpinion

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
structured_llm = llm.with_structured_output(JudicialOpinion)
"""

JUDGES_WITHOUT_STRUCTURED_OUTPUT = """
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
result = llm.invoke("grade this code")
"""


def test_structured_output_detected():
    repo = make_repo({"src/nodes/judges.py": JUDGES_WITH_STRUCTURED_OUTPUT})
    result = check_structured_output_enforcement(repo)
    assert result["found"] is True
    assert result["has_structured_output"] is True
    assert result["has_judicial_opinion_binding"] is True


def test_structured_output_missing():
    repo = make_repo({"src/nodes/judges.py": JUDGES_WITHOUT_STRUCTURED_OUTPUT})
    result = check_structured_output_enforcement(repo)
    assert result["has_structured_output"] is False
    assert result["has_judicial_opinion_binding"] is False


def test_structured_output_no_judges_file():
    repo = make_repo({"src/state.py": "x = 1"})
    result = check_structured_output_enforcement(repo)
    assert result["found"] is False


# ---------------------------------------------------------------------------
# clone_repo_sandboxed — sandbox safety (RISK-2)
# ---------------------------------------------------------------------------


def test_clone_bad_url_raises_runtime_error():
    from src.tools.repo_tools import clone_repo_sandboxed

    with pytest.raises(RuntimeError):
        clone_repo_sandboxed("https://github.com/this-does-not-exist-xyz/no-repo-here")


def test_clone_never_touches_cwd(tmp_path, monkeypatch):
    """Verify that a clone failure does not leave files in CWD."""
    import os
    monkeypatch.chdir(tmp_path)
    cwd_before = set(os.listdir(tmp_path))

    from src.tools.repo_tools import clone_repo_sandboxed

    with pytest.raises(RuntimeError):
        clone_repo_sandboxed("https://github.com/this-does-not-exist-xyz/no-repo-here")

    cwd_after = set(os.listdir(tmp_path))
    assert cwd_before == cwd_after, "Clone left files in CWD"
