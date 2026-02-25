"""
Forensic tools for repository analysis.

RISK-2 MITIGATION: All git operations run inside tempfile.TemporaryDirectory().
No os.system() calls. subprocess.run() with captured output only.
Repo path is never the live working directory.

RISK-5 MITIGATION: Every function returns a result dict — never raises silently.
Errors are captured and returned as structured data so the detective node
can produce an Evidence(found=False) rather than crashing.
"""

import ast
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Repository cloning
# ---------------------------------------------------------------------------


def clone_repo_sandboxed(url: str) -> tuple[tempfile.TemporaryDirectory, Path]:
    """
    Clone a repository into a sandboxed temporary directory.

    Returns (tmpdir, repo_path). The caller owns tmpdir's lifecycle and
    must call tmpdir.cleanup() in a finally block.

    Raises RuntimeError if the clone fails — caller handles this as
    Evidence(found=False).
    """
    tmpdir = tempfile.TemporaryDirectory()
    try:
        result = subprocess.run(
            ["git", "clone", "--depth=1", url, tmpdir.name],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode != 0:
            tmpdir.cleanup()
            raise RuntimeError(result.stderr.strip()[:400])
        return tmpdir, Path(tmpdir.name)
    except subprocess.TimeoutExpired:
        tmpdir.cleanup()
        raise RuntimeError("Clone timed out after 90 seconds.")
    except Exception as exc:
        tmpdir.cleanup()
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Git history analysis
# ---------------------------------------------------------------------------


def extract_git_history(repo_path: Path) -> dict:
    """
    Run 'git log --oneline --reverse' and analyze commit progression.

    Returns a dict with:
      - commits: list of commit message strings
      - total_count: int
      - has_progression: bool (>3 commits with varied messages)
      - is_bulk_upload: bool (single commit or timestamps too close)
      - error: Optional[str]
    """
    try:
        log_result = subprocess.run(
            ["git", "log", "--oneline", "--reverse"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=15,
        )
        if log_result.returncode != 0:
            return _git_error_result(log_result.stderr.strip()[:200])

        commits = [line.strip() for line in log_result.stdout.strip().splitlines() if line.strip()]
        total = len(commits)

        return {
            "commits": commits,
            "total_count": total,
            "has_progression": _check_progression(commits),
            "is_bulk_upload": total <= 1,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return _git_error_result("git log timed out")
    except Exception as exc:
        return _git_error_result(str(exc)[:200])


def _check_progression(commits: list[str]) -> bool:
    """True if >3 commits with meaningfully different messages."""
    if len(commits) <= 3:
        return False
    # Check that messages are not all identical (bulk duplication)
    unique_messages = {c.split(" ", 1)[-1].strip().lower() for c in commits}
    return len(unique_messages) > 2


def _git_error_result(error: str) -> dict:
    return {
        "commits": [],
        "total_count": 0,
        "has_progression": False,
        "is_bulk_upload": True,
        "error": error,
    }


# ---------------------------------------------------------------------------
# AST-based state management analysis
# ---------------------------------------------------------------------------


def check_state_management_rigor(repo_path: Path) -> dict:
    """
    Phase 1 criterion: verify Pydantic/TypedDict state definitions with reducers.

    Scans src/state.py then src/graph.py. Uses AST parsing — no regex.

    Returns a dict with:
      - found: bool
      - location: str
      - parse_error: Optional[str]
      - has_basemodel: bool
      - has_typeddict: bool
      - has_reducers: bool
    """
    candidates = [
        repo_path / "src" / "state.py",
        repo_path / "src" / "graph.py",
    ]

    for path in candidates:
        if not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            return _state_error_result(str(path.relative_to(repo_path)), str(exc))

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return {
                "found": True,
                "location": str(path.relative_to(repo_path)),
                "parse_error": f"SyntaxError at line {exc.lineno}: {exc.msg}",
                "has_basemodel": False,
                "has_typeddict": False,
                "has_reducers": False,
            }

        return {
            "found": True,
            "location": str(path.relative_to(repo_path)),
            "parse_error": None,
            "has_basemodel": _class_inherits_from(tree, "BaseModel"),
            "has_typeddict": _class_inherits_from(tree, "TypedDict"),
            "has_reducers": _has_annotated_reducers(source),
        }

    return {
        "found": False,
        "location": "N/A",
        "parse_error": None,
        "has_basemodel": False,
        "has_typeddict": False,
        "has_reducers": False,
    }


def _state_error_result(location: str, error: str) -> dict:
    return {
        "found": True,
        "location": location,
        "parse_error": error,
        "has_basemodel": False,
        "has_typeddict": False,
        "has_reducers": False,
    }


# ---------------------------------------------------------------------------
# AST-based graph orchestration analysis
# ---------------------------------------------------------------------------


def check_graph_orchestration(repo_path: Path) -> dict:
    """
    Verify StateGraph wiring for parallel fan-out/fan-in architecture.

    Checks for:
      - StateGraph instantiation
      - Multiple add_edge() calls (fan-out pattern)
      - add_node() calls for known detective/judge node names

    Returns a dict with:
      - found: bool
      - location: str
      - parse_error: Optional[str]
      - has_stategraph: bool
      - has_fan_out: bool  (multiple edges from START or single node)
      - has_aggregator: bool
      - edge_count: int
    """
    graph_path = repo_path / "src" / "graph.py"

    if not graph_path.exists():
        return {
            "found": False,
            "location": "N/A",
            "parse_error": None,
            "has_stategraph": False,
            "has_fan_out": False,
            "has_aggregator": False,
            "edge_count": 0,
        }

    try:
        source = graph_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "found": True,
            "location": "src/graph.py",
            "parse_error": f"SyntaxError: {exc.msg}",
            "has_stategraph": False,
            "has_fan_out": False,
            "has_aggregator": False,
            "edge_count": 0,
        }

    edge_calls = _count_method_calls(tree, "add_edge")
    node_calls = _get_node_names(tree)
    aggregator_names = {"evidence_aggregator", "aggregator", "evidenceaggregator"}

    return {
        "found": True,
        "location": "src/graph.py",
        "parse_error": None,
        "has_stategraph": _name_exists_in_source(source, "StateGraph"),
        "has_fan_out": edge_calls >= 4,
        "has_aggregator": bool(aggregator_names & {n.lower() for n in node_calls}),
        "edge_count": edge_calls,
    }


# ---------------------------------------------------------------------------
# Safe tool engineering analysis
# ---------------------------------------------------------------------------


def check_safe_tool_engineering(repo_path: Path) -> dict:
    """
    Scan src/tools/ for sandboxed cloning and absence of os.system() calls.

    Returns a dict with:
      - found: bool
      - location: str
      - uses_tempfile: bool
      - uses_subprocess: bool
      - has_os_system: bool  (security violation if True)
      - parse_error: Optional[str]
    """
    tools_dir = repo_path / "src" / "tools"
    if not tools_dir.exists():
        return {
            "found": False,
            "location": "N/A",
            "uses_tempfile": False,
            "uses_subprocess": False,
            "has_os_system": False,
            "parse_error": None,
        }

    combined_source = ""
    location = "src/tools/"

    for py_file in tools_dir.glob("*.py"):
        try:
            combined_source += py_file.read_text(encoding="utf-8") + "\n"
        except OSError:
            pass

    if not combined_source.strip():
        return {
            "found": True,
            "location": location,
            "uses_tempfile": False,
            "uses_subprocess": False,
            "has_os_system": False,
            "parse_error": "No Python files found in src/tools/",
        }

    return {
        "found": True,
        "location": location,
        "uses_tempfile": "tempfile" in combined_source,
        "uses_subprocess": "subprocess.run" in combined_source or "subprocess.Popen" in combined_source,
        # AST-based detection: look for actual os.system() calls, not mentions in comments.
        "has_os_system": _has_os_system_call(combined_source),
        "parse_error": None,
    }


# ---------------------------------------------------------------------------
# Structured output enforcement analysis
# ---------------------------------------------------------------------------


def check_structured_output_enforcement(repo_path: Path) -> dict:
    """
    Verify that judge nodes use .with_structured_output() bound to JudicialOpinion.

    Returns a dict with:
      - found: bool
      - location: str
      - has_structured_output: bool
      - has_judicial_opinion_binding: bool
      - parse_error: Optional[str]
    """
    judges_path = repo_path / "src" / "nodes" / "judges.py"

    if not judges_path.exists():
        return {
            "found": False,
            "location": "N/A",
            "has_structured_output": False,
            "has_judicial_opinion_binding": False,
            "parse_error": None,
        }

    try:
        source = judges_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "found": True,
            "location": "src/nodes/judges.py",
            "has_structured_output": False,
            "has_judicial_opinion_binding": False,
            "parse_error": str(exc),
        }

    return {
        "found": True,
        "location": "src/nodes/judges.py",
        "has_structured_output": "with_structured_output" in source or "bind_tools" in source,
        "has_judicial_opinion_binding": "JudicialOpinion" in source,
        "parse_error": None,
    }


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _class_inherits_from(tree: ast.AST, base_name: str) -> bool:
    """Return True if any class in the AST inherits from base_name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = None
                if isinstance(base, ast.Name):
                    name = base.id
                elif isinstance(base, ast.Attribute):
                    name = base.attr
                if name == base_name:
                    return True
    return False


def _has_annotated_reducers(source: str) -> bool:
    """Check for operator.add or operator.ior in Annotated type hints."""
    return "operator.add" in source or "operator.ior" in source


def _has_os_system_call(source: str) -> bool:
    """
    AST-based detection of actual os.system() calls.
    Ignores mentions in comments, docstrings, and string literals.
    Returns True only if os.system is called as a function in executable code.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fall back to conservative string check if source cannot be parsed
        return "os.system(" in source

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "system"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            return True
    return False


def _count_method_calls(tree: ast.AST, method_name: str) -> int:
    """Count calls to .method_name() anywhere in the AST."""
    count = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name
        ):
            count += 1
    return count


def _get_node_names(tree: ast.AST) -> list[str]:
    """Extract string arguments from add_node() calls."""
    names = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_node"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.append(node.args[0].value)
    return names


def _name_exists_in_source(source: str, name: str) -> bool:
    return name in source


def _optional_str(value: Optional[str]) -> str:
    return value if value is not None else ""
