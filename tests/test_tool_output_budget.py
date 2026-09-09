"""验证 14.5 全局工具输出预算、外置结果和虚拟续读。"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from mini_deer_agent.agents.middleware import (
    TOOL_OUTPUT_META_KEY,
    RunOutputStore,
    ToolOutputBudget,
    ToolOutputBudgetPolicy,
    tool_result_meta,
)


def _policy() -> ToolOutputBudgetPolicy:
    return ToolOutputBudgetPolicy(
        max_inline_chars=1_024,
        sample_chars=100,
        read_chunk_chars=400,
    )


def _request(
    name: str,
    *,
    run_id: str | None = None,
    call_id: str = "call-1",
    args: dict[str, object] | None = None,
) -> ToolCallRequest:
    runtime = (
        SimpleNamespace(config={"configurable": {"run_id": run_id}})
        if run_id is not None
        else None
    )
    return ToolCallRequest(
        tool_call=cast(
            Any,
            {
                "name": name,
                "args": args or {},
                "id": call_id,
                "type": "tool_call",
            },
        ),
        tool=None,
        state={},
        runtime=cast(Any, runtime),
    )


def _message(request: ToolCallRequest, content: str) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=str(request.tool_call["id"]),
        name=str(request.tool_call["name"]),
    )


def test_small_result_is_preserved_verbatim(tmp_path: Path) -> None:
    budget = ToolOutputBudget(RunOutputStore(tmp_path), _policy())
    request = _request("small", run_id=str(uuid4()))

    result = budget.wrap_tool_call(
        request,
        lambda current: _message(current, "small useful result"),
    )

    assert isinstance(result, ToolMessage)
    assert result.text == "small useful result"
    assert TOOL_OUTPUT_META_KEY not in result.additional_kwargs
    assert list(tmp_path.glob("**/*")) == []


def test_large_json_is_summarized_and_stored_losslessly(tmp_path: Path) -> None:
    run_id = str(uuid4())
    store = RunOutputStore(tmp_path)
    budget = ToolOutputBudget(store, _policy())
    content = json.dumps(
        {
            "records": [
                {"id": index, "status": "ok", "detail": "x" * 30}
                for index in range(80)
            ],
            "last_error": "target-marker",
        },
        ensure_ascii=False,
    )

    result = budget.wrap_tool_call(
        _request("large_json", run_id=run_id, call_id="json-call"),
        lambda current: _message(current, content),
    )

    assert isinstance(result, ToolMessage)
    payload = json.loads(result.text)
    meta = result.additional_kwargs[TOOL_OUTPUT_META_KEY]
    assert len(result.text) <= _policy().max_inline_chars
    assert payload["kind"] == "tool_output_reference"
    assert payload["format"] == "json"
    assert payload["structure"]["container"] == "object"
    assert set(payload["structure"]["keys"]) == {"records", "last_error"}
    assert payload["stored"] is True
    assert payload["path"].startswith("run-output/large_json-")
    assert meta["original_chars"] == len(content)
    assert tool_result_meta(result).status == "partial_success"
    stored_files = [path for path in tmp_path.glob("**/*") if path.is_file()]
    assert len(stored_files) == 1
    assert stored_files[0].read_text(encoding="utf-8") == content


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("a,b,c\n" + "1,2,3\n" * 300, "csv"),
        ("a\tb\tc\n" + "1\t2\t3\n" * 300, "tsv"),
        ("<root>" + "<item>value</item>" * 200 + "</root>", "xml"),
        ("root:\n  child: value\n" * 100, "yaml"),
        ("HEAD\n" + "INFO operation completed\n" * 200 + "TAIL", "text"),
    ],
)
def test_structure_formats_are_detected_without_an_llm(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    budget = ToolOutputBudget(RunOutputStore(tmp_path), _policy())
    result = budget.wrap_tool_call(
        _request("structured", run_id=str(uuid4())),
        lambda current: _message(current, content),
    )

    assert isinstance(result, ToolMessage)
    payload = json.loads(result.text)
    assert payload["format"] == expected
    assert payload["sample"]["head"]
    assert payload["sample"]["tail"]


def test_virtual_read_handles_long_single_line_and_is_run_scoped(
    tmp_path: Path,
) -> None:
    first_run = str(uuid4())
    second_run = str(uuid4())
    store = RunOutputStore(tmp_path)
    budget = ToolOutputBudget(store, _policy())
    content = "BEGIN-" + "x" * 2_000 + "-END"
    original = budget.wrap_tool_call(
        _request("large_line", run_id=first_run, call_id="long-line"),
        lambda current: _message(current, content),
    )
    assert isinstance(original, ToolMessage)
    path = json.loads(original.text)["path"]

    called = False

    def must_not_execute(_request: ToolCallRequest) -> ToolMessage:
        nonlocal called
        called = True
        raise AssertionError("virtual read must be intercepted")

    first = budget.wrap_tool_call(
        _request(
            "read_file",
            run_id=first_run,
            call_id="read-1",
            args={"path": path, "start_line": 1, "limit": 1},
        ),
        must_not_execute,
    )
    assert isinstance(first, ToolMessage)
    first_payload = json.loads(first.text)
    assert called is False
    assert first_payload["virtual_chunks"] is True
    assert first_payload["next_line"] == 2
    assert first_payload["lines"][0].startswith("BEGIN-")
    assert len(first_payload["lines"][0]) == 400

    cross_run = budget.wrap_tool_call(
        _request(
            "read_file",
            run_id=second_run,
            call_id="read-cross-run",
            args={"path": path},
        ),
        must_not_execute,
    )
    assert isinstance(cross_run, ToolMessage)
    assert cross_run.status == "error"
    assert tool_result_meta(cross_run).error_type == "run_output_not_found"


def test_storage_failure_returns_explicit_bounded_fallback(tmp_path: Path) -> None:
    unusable_root = tmp_path / "not-a-directory"
    unusable_root.write_text("occupied", encoding="utf-8")
    budget = ToolOutputBudget(RunOutputStore(unusable_root), _policy())
    content = "HEAD-MARKER\n" + "x" * 3_000 + "\nTAIL-MARKER"

    result = budget.wrap_tool_call(
        _request("large_log", run_id=str(uuid4())),
        lambda current: _message(current, content),
    )

    assert isinstance(result, ToolMessage)
    payload = json.loads(result.text)
    assert len(result.text) <= _policy().max_inline_chars
    assert payload["stored"] is False
    assert payload["storage_error"] == "run_output_storage_unavailable"
    assert payload["next_action"]["action"] == "use_bounded_sample"
    assert "HEAD-MARKER" in payload["sample"]["head"]
    assert "TAIL-MARKER" in payload["sample"]["tail"]
    assert content not in result.text


def test_pathological_structure_still_produces_valid_bounded_json(
    tmp_path: Path,
) -> None:
    budget = ToolOutputBudget(RunOutputStore(tmp_path), _policy())
    content = json.dumps(
        {f"key-{index}-" + "k" * 500: "v" * 500 for index in range(40)}
    )

    result = budget.wrap_tool_call(
        _request("wide_json", run_id=str(uuid4())),
        lambda current: _message(current, content),
    )

    assert isinstance(result, ToolMessage)
    assert len(result.text) <= _policy().max_inline_chars
    payload = json.loads(result.text)
    assert payload["kind"] == "tool_output_reference"
    assert payload["stored"] is True
