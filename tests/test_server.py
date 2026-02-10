"""Tests for Jenkins MCP Server tools — all Jenkins calls are mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import jenkins
import pytest

from jenkins_mcp.server import (
    cancel_build as _cancel_build_tool,
    fetch_build_artifact as _fetch_build_artifact_tool,
    get_build_log as _get_build_log_tool,
    get_job_parameters as _get_job_parameters_tool,
    get_job_status as _get_job_status_tool,
    list_build_artifacts as _list_build_artifacts_tool,
    list_triggered_jobs as _list_triggered_jobs_tool,
    trigger_job as _trigger_job_tool,
)
from jenkins_mcp.trigger_store import TriggerStore

# @mcp.tool wraps functions as FunctionTool objects; access the
# underlying plain function via the `.fn` attribute for direct testing.
trigger_job = _trigger_job_tool.fn
get_job_parameters = _get_job_parameters_tool.fn
get_job_status = _get_job_status_tool.fn
get_build_log = _get_build_log_tool.fn
cancel_build = _cancel_build_tool.fn
list_build_artifacts = _list_build_artifacts_tool.fn
fetch_build_artifact = _fetch_build_artifact_tool.fn
list_triggered_jobs = _list_triggered_jobs_tool.fn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_client():
    """Return a MagicMock that replaces jenkins.Jenkins."""
    with patch("jenkins_mcp.server.get_client") as patched:
        client = MagicMock(spec=jenkins.Jenkins)
        patched.return_value = client
        yield client


@pytest.fixture
def tmp_store(tmp_path: Path):
    """Provide a TriggerStore backed by a temp file and patch get_store."""
    store = TriggerStore(path=tmp_path / "triggered_jobs.json")
    with patch("jenkins_mcp.server.get_store", return_value=store):
        yield store


# ---------------------------------------------------------------------------
# trigger_job
# ---------------------------------------------------------------------------
class TestTriggerJob:
    @pytest.fixture(autouse=True)
    def _with_store(self, tmp_store):
        """Every trigger_job test gets a clean temporary store."""
        self.store = tmp_store

    def test_trigger_success_with_build_number(self, mock_client):
        """Trigger a job and successfully resolve the build number."""
        mock_client.build_job.return_value = 101  # queue_id
        mock_client.get_queue_item.return_value = {
            "executable": {"number": 42, "url": "http://j/job/test/42/"}
        }

        with patch("jenkins_mcp.server.time.sleep"):
            result = trigger_job("my-job", parameters={"BRANCH": "main"})

        assert result["success"] is True
        assert result["queue_id"] == 101
        assert result["build_number"] == 42
        assert "my-job" in result["message"]
        mock_client.build_job.assert_called_once_with(
            "my-job", parameters={"BRANCH": "main"}
        )

    def test_trigger_success_without_build_number(self, mock_client):
        """Trigger a job but build number is not resolved within timeout."""
        mock_client.build_job.return_value = 101
        # Queue item never has an executable
        mock_client.get_queue_item.return_value = {"executable": None}

        with patch("jenkins_mcp.server.time.sleep"):
            result = trigger_job("my-job")

        assert result["success"] is True
        assert result["queue_id"] == 101
        assert "build_number" not in result
        assert "not yet available" in result["message"]

    def test_trigger_queue_poll_exception_then_success(self, mock_client):
        """Queue polling raises exception a few times then succeeds."""
        mock_client.build_job.return_value = 200
        mock_client.get_queue_item.side_effect = [
            jenkins.JenkinsException("not ready"),
            jenkins.JenkinsException("not ready"),
            {"executable": {"number": 7}},
        ]

        with patch("jenkins_mcp.server.time.sleep"):
            result = trigger_job("retry-job")

        assert result["success"] is True
        assert result["build_number"] == 7

    def test_trigger_without_parameters(self, mock_client):
        """Trigger a job with no parameters."""
        mock_client.build_job.return_value = 50
        mock_client.get_queue_item.return_value = {
            "executable": {"number": 1}
        }

        with patch("jenkins_mcp.server.time.sleep"):
            result = trigger_job("simple-job")

        assert result["success"] is True
        mock_client.build_job.assert_called_once_with(
            "simple-job", parameters=None
        )

    def test_trigger_persists_record(self, mock_client):
        """Triggered job is saved to the store."""
        mock_client.build_job.return_value = 300
        mock_client.get_queue_item.return_value = {
            "executable": {"number": 15}
        }

        with patch("jenkins_mcp.server.time.sleep"):
            trigger_job("persist-job", parameters={"X": "1"})

        records = self.store.list_all()
        assert len(records) == 1
        rec = records[0]
        assert rec["job_name"] == "persist-job"
        assert rec["parameters"] == {"X": "1"}
        assert rec["build_number"] == 15
        assert rec["queue_id"] == 300
        assert rec["status"] == "RUNNING"
        assert "trigger_time" in rec

    def test_trigger_persists_queued_record(self, mock_client):
        """Record marked QUEUED when build number not resolved."""
        mock_client.build_job.return_value = 301
        mock_client.get_queue_item.return_value = {"executable": None}

        with patch("jenkins_mcp.server.time.sleep"):
            trigger_job("queued-job")

        records = self.store.list_all()
        assert records[0]["status"] == "QUEUED"
        assert records[0]["build_number"] is None

    def test_trigger_jenkins_exception(self, mock_client):
        """build_job raises JenkinsException."""
        mock_client.build_job.side_effect = jenkins.JenkinsException("no such job")

        result = trigger_job("bad-job")

        assert result["error"] is True
        assert "no such job" in result["message"]

    def test_trigger_missing_url(self):
        """get_client raises ValueError when JENKINS_URL is missing."""
        with patch("jenkins_mcp.server.get_client") as patched:
            patched.side_effect = ValueError("JENKINS_URL environment variable is required.")
            result = trigger_job("any-job")

        assert result["error"] is True
        assert "JENKINS_URL" in result["message"]


# ---------------------------------------------------------------------------
# get_job_parameters
# ---------------------------------------------------------------------------
class TestGetJobParameters:
    def test_parameters_returned(self, mock_client):
        """Job with two parameters."""
        mock_client.get_job_info.return_value = {
            "property": [
                {
                    "parameterDefinitions": [
                        {
                            "name": "BRANCH",
                            "type": "StringParameterDefinition",
                            "description": "Git branch",
                            "defaultParameterValue": {"value": "main"},
                        },
                        {
                            "name": "DEPLOY",
                            "type": "BooleanParameterDefinition",
                            "description": "Deploy after build",
                            "defaultParameterValue": {"value": False},
                            "choices": None,
                        },
                    ]
                }
            ]
        }

        result = get_job_parameters("my-job")

        assert result["success"] is True
        assert result["parameter_count"] == 2
        params = result["parameters"]
        assert params[0]["name"] == "BRANCH"
        assert params[0]["default_value"] == "main"
        assert params[1]["name"] == "DEPLOY"
        assert params[1]["default_value"] is False

    def test_no_parameters(self, mock_client):
        """Job with no parameters."""
        mock_client.get_job_info.return_value = {"property": []}

        result = get_job_parameters("no-param-job")

        assert result["success"] is True
        assert result["parameter_count"] == 0
        assert result["parameters"] == []

    def test_choice_parameter(self, mock_client):
        """Job with a choice parameter."""
        mock_client.get_job_info.return_value = {
            "property": [
                {
                    "parameterDefinitions": [
                        {
                            "name": "ENV",
                            "type": "ChoiceParameterDefinition",
                            "description": "Target environment",
                            "defaultParameterValue": {"value": "staging"},
                            "choices": ["staging", "production"],
                        }
                    ]
                }
            ]
        }

        result = get_job_parameters("choice-job")

        assert result["parameters"][0]["choices"] == ["staging", "production"]

    def test_jenkins_exception(self, mock_client):
        mock_client.get_job_info.side_effect = jenkins.JenkinsException("not found")

        result = get_job_parameters("missing-job")

        assert result["error"] is True


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------
class TestGetJobStatus:
    def test_specific_build(self, mock_client):
        """Query a specific build number."""
        mock_client.get_build_info.return_value = {
            "number": 10,
            "result": "SUCCESS",
            "building": False,
            "timestamp": 1700000000000,
            "duration": 30000,
            "estimatedDuration": 25000,
            "displayName": "#10",
            "url": "http://j/job/test/10/",
        }

        result = get_job_status("my-job", build_number=10)

        assert result["success"] is True
        assert result["build_number"] == 10
        assert result["result"] == "SUCCESS"
        assert result["building"] is False
        assert result["duration_ms"] == 30000
        mock_client.get_build_info.assert_called_once_with("my-job", 10)

    def test_latest_build(self, mock_client):
        """When no build_number provided, use latest."""
        mock_client.get_job_info.return_value = {
            "lastBuild": {"number": 5}
        }
        mock_client.get_build_info.return_value = {
            "number": 5,
            "result": None,
            "building": True,
            "timestamp": 1700000000000,
            "duration": 0,
            "estimatedDuration": 60000,
            "displayName": "#5",
            "url": "http://j/job/test/5/",
        }

        result = get_job_status("my-job")

        assert result["success"] is True
        assert result["build_number"] == 5
        assert result["building"] is True
        assert result["result"] is None

    def test_no_builds(self, mock_client):
        """Job exists but has no builds."""
        mock_client.get_job_info.return_value = {"lastBuild": None}

        result = get_job_status("empty-job")

        assert result["success"] is True
        assert "No builds found" in result["message"]

    def test_start_time_formatting(self, mock_client):
        """Verify timestamp is converted to ISO format."""
        mock_client.get_build_info.return_value = {
            "number": 1,
            "result": "FAILURE",
            "building": False,
            "timestamp": 1609459200000,  # 2021-01-01T00:00:00Z
            "duration": 5000,
            "estimatedDuration": 5000,
            "displayName": "#1",
            "url": "",
        }

        result = get_job_status("ts-job", build_number=1)

        assert result["start_time"] is not None
        assert "2021-01-01" in result["start_time"]

    def test_jenkins_exception(self, mock_client):
        mock_client.get_build_info.side_effect = jenkins.JenkinsException("error")

        result = get_job_status("bad-job", build_number=1)

        assert result["error"] is True


# ---------------------------------------------------------------------------
# get_build_log
# ---------------------------------------------------------------------------
class TestGetBuildLog:
    """Tests for paginated log retrieval."""

    SAMPLE_LOG = "\n".join(f"line {i}" for i in range(200))  # 200 lines

    def test_forward_default(self, mock_client):
        """Default forward pagination: first 100 lines."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log("my-job", build_number=1)

        assert result["success"] is True
        assert result["total_lines"] == 200
        assert result["start_line"] == 0
        assert result["lines_returned"] == 100
        assert result["has_more"] is True
        assert result["from_end"] is False
        assert result["log"].startswith("line 0")

    def test_forward_with_offset(self, mock_client):
        """Forward pagination starting at line 150."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log("my-job", build_number=1, start_line=150, max_lines=100)

        assert result["start_line"] == 150
        assert result["lines_returned"] == 50  # only 50 lines left
        assert result["has_more"] is False

    def test_forward_exact_boundary(self, mock_client):
        """Requesting exactly the remaining lines."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log("my-job", build_number=1, start_line=100, max_lines=100)

        assert result["lines_returned"] == 100
        assert result["has_more"] is False

    def test_from_end_default(self, mock_client):
        """from_end=True with default offset: last 100 lines."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log("my-job", build_number=1, from_end=True)

        assert result["success"] is True
        assert result["start_line"] == 100  # begins at line 100
        assert result["lines_returned"] == 100
        assert result["has_more"] is True
        assert result["log"].startswith("line 100")
        assert result["log"].endswith("line 199")

    def test_from_end_with_offset(self, mock_client):
        """from_end=True, skip last 50 lines, take 50."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log(
            "my-job", build_number=1, start_line=50, max_lines=50, from_end=True
        )

        # end_idx = 200 - 50 = 150, begin_idx = 150 - 50 = 100
        assert result["start_line"] == 100
        assert result["lines_returned"] == 50
        assert result["has_more"] is True
        lines = result["log"].split("\n")
        assert lines[0] == "line 100"
        assert lines[-1] == "line 149"

    def test_from_end_all_lines(self, mock_client):
        """from_end requesting more lines than exist."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log(
            "my-job", build_number=1, max_lines=500, from_end=True
        )

        assert result["start_line"] == 0
        assert result["lines_returned"] == 200
        assert result["has_more"] is False

    def test_from_end_offset_exceeds_total(self, mock_client):
        """from_end with start_line larger than total lines."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log(
            "my-job", build_number=1, start_line=300, max_lines=50, from_end=True
        )

        assert result["lines_returned"] == 0
        assert result["has_more"] is False

    def test_empty_log(self, mock_client):
        """Empty console output."""
        mock_client.get_build_console_output.return_value = ""

        result = get_build_log("my-job", build_number=1)

        assert result["success"] is True
        assert result["total_lines"] == 0
        assert result["lines_returned"] == 0
        assert result["has_more"] is False

    def test_forward_start_beyond_total(self, mock_client):
        """Forward with start_line beyond total lines."""
        mock_client.get_build_console_output.return_value = self.SAMPLE_LOG

        result = get_build_log("my-job", build_number=1, start_line=999)

        assert result["lines_returned"] == 0
        assert result["has_more"] is False

    def test_jenkins_exception(self, mock_client):
        mock_client.get_build_console_output.side_effect = jenkins.JenkinsException(
            "not found"
        )

        result = get_build_log("bad-job", build_number=1)

        assert result["error"] is True


# ---------------------------------------------------------------------------
# cancel_build
# ---------------------------------------------------------------------------
class TestCancelBuild:
    def test_cancel_success(self, mock_client):
        """Successfully cancel a running build."""
        mock_client.stop_build.return_value = None

        result = cancel_build("my-job", build_number=10)

        assert result["success"] is True
        assert result["build_number"] == 10
        assert "cancelled" in result["message"]
        mock_client.stop_build.assert_called_once_with("my-job", 10)

    def test_cancel_jenkins_exception(self, mock_client):
        """stop_build raises JenkinsException."""
        mock_client.stop_build.side_effect = jenkins.JenkinsException(
            "build not running"
        )

        result = cancel_build("my-job", build_number=99)

        assert result["error"] is True
        assert "build not running" in result["message"]


# ---------------------------------------------------------------------------
# list_build_artifacts
# ---------------------------------------------------------------------------
class TestListBuildArtifacts:
    def test_list_with_artifacts(self, mock_client):
        """Build with multiple artifacts."""
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/5/",
            "artifacts": [
                {
                    "displayPath": "app.jar",
                    "fileName": "app.jar",
                    "relativePath": "target/app.jar",
                },
                {
                    "displayPath": "report.html",
                    "fileName": "report.html",
                    "relativePath": "reports/report.html",
                },
            ],
        }

        result = list_build_artifacts("my-job", build_number=5)

        assert result["success"] is True
        assert result["build_number"] == 5
        assert result["artifact_count"] == 2
        assert result["artifacts"][0]["file_name"] == "app.jar"
        assert result["artifacts"][0]["relative_path"] == "target/app.jar"
        assert result["artifacts"][0]["download_url"] == (
            "http://j/job/my-job/5/artifact/target/app.jar"
        )
        assert result["artifacts"][1]["file_name"] == "report.html"

    def test_list_no_artifacts(self, mock_client):
        """Build with no artifacts."""
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/3/",
            "artifacts": [],
        }

        result = list_build_artifacts("my-job", build_number=3)

        assert result["success"] is True
        assert result["artifact_count"] == 0
        assert result["artifacts"] == []

    def test_list_latest_build(self, mock_client):
        """No build_number provided — use latest."""
        mock_client.get_job_info.return_value = {
            "lastBuild": {"number": 10}
        }
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/10/",
            "artifacts": [
                {
                    "displayPath": "out.log",
                    "fileName": "out.log",
                    "relativePath": "out.log",
                }
            ],
        }

        result = list_build_artifacts("my-job")

        assert result["success"] is True
        assert result["build_number"] == 10
        assert result["artifact_count"] == 1

    def test_list_no_builds(self, mock_client):
        """Job has no builds at all."""
        mock_client.get_job_info.return_value = {"lastBuild": None}

        result = list_build_artifacts("empty-job")

        assert result["success"] is True
        assert "No builds found" in result["message"]

    def test_list_jenkins_exception(self, mock_client):
        mock_client.get_build_info.side_effect = jenkins.JenkinsException("error")

        result = list_build_artifacts("bad-job", build_number=1)

        assert result["error"] is True


# ---------------------------------------------------------------------------
# fetch_build_artifact
# ---------------------------------------------------------------------------
class TestFetchBuildArtifact:
    def test_fetch_text_artifact(self, mock_client):
        """Download a text artifact."""
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/5/",
        }
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "text/plain; charset=utf-8"}
        mock_response.text = "Hello, world!\nLine 2\n"
        mock_response.content = b"Hello, world!\nLine 2\n"
        mock_client.jenkins_request.return_value = mock_response

        result = fetch_build_artifact("my-job", 5, "output/result.txt")

        assert result["success"] is True
        assert result["encoding"] == "text"
        assert result["content"] == "Hello, world!\nLine 2\n"
        assert result["file_name"] == "result.txt"
        assert result["size_bytes"] == len(b"Hello, world!\nLine 2\n")

    def test_fetch_json_artifact(self, mock_client):
        """Download a JSON artifact (treated as text)."""
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/5/",
        }
        json_body = '{"status": "ok"}'
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = json_body
        mock_response.content = json_body.encode()
        mock_client.jenkins_request.return_value = mock_response

        result = fetch_build_artifact("my-job", 5, "data.json")

        assert result["success"] is True
        assert result["encoding"] == "text"
        assert result["content"] == json_body

    def test_fetch_xml_artifact(self, mock_client):
        """Download an XML artifact (treated as text)."""
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/5/",
        }
        xml_body = "<root><item/></root>"
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/xml"}
        mock_response.text = xml_body
        mock_response.content = xml_body.encode()
        mock_client.jenkins_request.return_value = mock_response

        result = fetch_build_artifact("my-job", 5, "report.xml")

        assert result["encoding"] == "text"

    def test_fetch_binary_artifact(self, mock_client):
        """Download a binary artifact — returns base64."""
        import base64

        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/5/",
        }
        binary_data = bytes(range(256))
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "application/octet-stream"}
        mock_response.content = binary_data
        mock_client.jenkins_request.return_value = mock_response

        result = fetch_build_artifact("my-job", 5, "build/app.jar")

        assert result["success"] is True
        assert result["encoding"] == "base64"
        assert result["file_name"] == "app.jar"
        assert result["size_bytes"] == 256
        # Verify we can decode it back
        decoded = base64.b64decode(result["content"])
        assert decoded == binary_data

    def test_fetch_no_build_url(self, mock_client):
        """Build info has no URL — returns error."""
        mock_client.get_build_info.return_value = {"url": ""}

        result = fetch_build_artifact("my-job", 5, "any.txt")

        assert result["error"] is True
        assert "Cannot determine build URL" in result["message"]

    def test_fetch_jenkins_exception(self, mock_client):
        mock_client.get_build_info.side_effect = jenkins.JenkinsException(
            "not found"
        )

        result = fetch_build_artifact("bad-job", 1, "any.txt")

        assert result["error"] is True

    def test_fetch_artifact_nested_path(self, mock_client):
        """Artifact with deeply nested relative path."""
        mock_client.get_build_info.return_value = {
            "url": "http://j/job/my-job/1/",
        }
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = "<html></html>"
        mock_response.content = b"<html></html>"
        mock_client.jenkins_request.return_value = mock_response

        result = fetch_build_artifact(
            "my-job", 1, "a/b/c/index.html"
        )

        assert result["success"] is True
        assert result["file_name"] == "index.html"
        assert result["artifact_path"] == "a/b/c/index.html"


# ---------------------------------------------------------------------------
# TriggerStore (unit tests)
# ---------------------------------------------------------------------------
class TestTriggerStore:
    def test_add_and_list(self, tmp_path: Path):
        store = TriggerStore(path=tmp_path / "store.json")
        store.add(job_name="j1", parameters=None, queue_id=1, build_number=10)
        store.add(job_name="j2", parameters={"A": "1"}, queue_id=2, build_number=None)

        records = store.list_all()
        assert len(records) == 2
        # newest first
        assert records[0]["job_name"] == "j2"
        assert records[1]["job_name"] == "j1"

    def test_update_record(self, tmp_path: Path):
        store = TriggerStore(path=tmp_path / "store.json")
        store.add(job_name="j1", parameters=None, queue_id=100, build_number=None)

        store.update_record(100, build_number=5, status="SUCCESS")

        rec = store.list_all()[0]
        assert rec["build_number"] == 5
        assert rec["status"] == "SUCCESS"

    def test_clear(self, tmp_path: Path):
        store = TriggerStore(path=tmp_path / "store.json")
        store.add(job_name="j1", parameters=None, queue_id=1, build_number=1)
        store.clear()
        assert store.list_all() == []

    def test_persistence_across_instances(self, tmp_path: Path):
        path = tmp_path / "store.json"
        store1 = TriggerStore(path=path)
        store1.add(job_name="j1", parameters=None, queue_id=1, build_number=1)

        # New instance reads from same file
        store2 = TriggerStore(path=path)
        assert len(store2.list_all()) == 1

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "store.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        store = TriggerStore(path=path)
        assert store.list_all() == []

    def test_corrupt_file(self, tmp_path: Path):
        path = tmp_path / "store.json"
        path.write_text("{not valid json")
        store = TriggerStore(path=path)
        assert store.list_all() == []


# ---------------------------------------------------------------------------
# list_triggered_jobs
# ---------------------------------------------------------------------------
class TestListTriggeredJobs:
    def test_empty_store(self, mock_client, tmp_store):
        """No records yet."""
        result = list_triggered_jobs()

        assert result["success"] is True
        assert result["total"] == 0
        assert "No jobs" in result["message"]

    def test_sync_running_to_success(self, mock_client, tmp_store):
        """A RUNNING job is updated to SUCCESS on query."""
        tmp_store.add(
            job_name="my-job", parameters=None, queue_id=10, build_number=5
        )
        mock_client.get_build_info.return_value = {
            "building": False,
            "result": "SUCCESS",
        }

        result = list_triggered_jobs()

        assert result["success"] is True
        assert result["total"] == 1
        assert result["records"][0]["status"] == "SUCCESS"
        # Store is also updated persistently
        assert tmp_store.list_all()[0]["status"] == "SUCCESS"

    def test_sync_running_to_failure(self, mock_client, tmp_store):
        """A RUNNING job is updated to FAILURE."""
        tmp_store.add(
            job_name="fail-job", parameters=None, queue_id=20, build_number=3
        )
        mock_client.get_build_info.return_value = {
            "building": False,
            "result": "FAILURE",
        }

        result = list_triggered_jobs()

        assert result["records"][0]["status"] == "FAILURE"

    def test_sync_still_running(self, mock_client, tmp_store):
        """A job that is still building stays RUNNING."""
        tmp_store.add(
            job_name="busy-job", parameters=None, queue_id=30, build_number=7
        )
        mock_client.get_build_info.return_value = {
            "building": True,
            "result": None,
        }

        result = list_triggered_jobs()

        assert result["records"][0]["status"] == "RUNNING"

    def test_sync_queued_resolves_build_number(self, mock_client, tmp_store):
        """A QUEUED job gets its build_number resolved and status synced."""
        tmp_store.add(
            job_name="q-job", parameters={"K": "V"}, queue_id=40, build_number=None
        )
        mock_client.get_queue_item.return_value = {
            "executable": {"number": 99}
        }
        mock_client.get_build_info.return_value = {
            "building": True,
            "result": None,
        }

        result = list_triggered_jobs()

        rec = result["records"][0]
        assert rec["build_number"] == 99
        assert rec["status"] == "RUNNING"

    def test_sync_queued_still_no_build(self, mock_client, tmp_store):
        """QUEUED job where queue item still has no executable."""
        tmp_store.add(
            job_name="wait-job", parameters=None, queue_id=50, build_number=None
        )
        mock_client.get_queue_item.return_value = {"executable": None}

        result = list_triggered_jobs()

        rec = result["records"][0]
        assert rec["build_number"] is None
        assert rec["status"] == "QUEUED"

    def test_terminal_states_not_re_queried(self, mock_client, tmp_store):
        """Jobs in terminal states (SUCCESS/FAILURE/ABORTED) are not queried."""
        tmp_store.add(
            job_name="done-job", parameters=None, queue_id=60, build_number=1
        )
        tmp_store.update_record(60, status="SUCCESS")

        result = list_triggered_jobs()

        assert result["records"][0]["status"] == "SUCCESS"
        mock_client.get_build_info.assert_not_called()

    def test_multiple_records(self, mock_client, tmp_store):
        """Multiple records with mixed states."""
        tmp_store.add(
            job_name="job-a", parameters=None, queue_id=1, build_number=1
        )
        tmp_store.update_record(1, status="SUCCESS")
        tmp_store.add(
            job_name="job-b", parameters=None, queue_id=2, build_number=2
        )
        mock_client.get_build_info.return_value = {
            "building": False,
            "result": "FAILURE",
        }

        result = list_triggered_jobs()

        assert result["total"] == 2
        # newest first
        assert result["records"][0]["job_name"] == "job-b"
        assert result["records"][0]["status"] == "FAILURE"
        assert result["records"][1]["job_name"] == "job-a"
        assert result["records"][1]["status"] == "SUCCESS"

    def test_jenkins_error_during_sync_is_graceful(self, mock_client, tmp_store):
        """If Jenkins errors during sync, the record keeps its old status."""
        tmp_store.add(
            job_name="err-job", parameters=None, queue_id=70, build_number=8
        )
        mock_client.get_build_info.side_effect = jenkins.JenkinsException("timeout")

        result = list_triggered_jobs()

        # Still returns the records, status unchanged
        assert result["success"] is True
        assert result["records"][0]["status"] == "RUNNING"
