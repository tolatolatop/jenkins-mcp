"""Jenkins MCP Server — manage Jenkins jobs via MCP tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jenkins
from fastmcp import FastMCP

from jenkins_mcp.jenkins_client import get_client

mcp = FastMCP("Jenkins MCP Server")


def _format_error(e: Exception) -> dict[str, Any]:
    """Format an exception into a consistent error response."""
    return {"error": True, "message": str(e)}


# ---------------------------------------------------------------------------
# Tool 1: trigger_job
# ---------------------------------------------------------------------------
@mcp.tool
def trigger_job(job_name: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Trigger a Jenkins job build, optionally with parameters.

    Args:
        job_name: Full name of the Jenkins job (use '/' for folder paths).
        parameters: Optional dict of build parameters (key-value pairs).

    Returns:
        A dict containing the queue_id of the triggered build.
    """
    try:
        client = get_client()
        queue_id = client.build_job(job_name, parameters=parameters)
        return {
            "success": True,
            "job_name": job_name,
            "queue_id": queue_id,
            "message": f"Job '{job_name}' has been triggered. Queue ID: {queue_id}",
        }
    except jenkins.JenkinsException as e:
        return _format_error(e)
    except ValueError as e:
        return _format_error(e)


# ---------------------------------------------------------------------------
# Tool 2: get_job_parameters
# ---------------------------------------------------------------------------
@mcp.tool
def get_job_parameters(job_name: str) -> dict[str, Any]:
    """Get the parameter definitions for a Jenkins job.

    Args:
        job_name: Full name of the Jenkins job.

    Returns:
        A dict containing a list of parameter definitions with name, type,
        default value and description for each parameter.
    """
    try:
        client = get_client()
        job_info = client.get_job_info(job_name)

        params: list[dict[str, Any]] = []
        for prop in job_info.get("property", []):
            param_defs = prop.get("parameterDefinitions")
            if param_defs:
                for p in param_defs:
                    default_value = p.get("defaultParameterValue", {})
                    params.append(
                        {
                            "name": p.get("name", ""),
                            "type": p.get("type", ""),
                            "description": p.get("description", ""),
                            "default_value": default_value.get("value")
                            if default_value
                            else None,
                            "choices": p.get("choices")
                        }
                    )

        return {
            "success": True,
            "job_name": job_name,
            "parameter_count": len(params),
            "parameters": params,
        }
    except jenkins.JenkinsException as e:
        return _format_error(e)
    except ValueError as e:
        return _format_error(e)


# ---------------------------------------------------------------------------
# Tool 3: get_job_status
# ---------------------------------------------------------------------------
@mcp.tool
def get_job_status(
    job_name: str, build_number: int | None = None
) -> dict[str, Any]:
    """Get the status of a Jenkins job build.

    Args:
        job_name: Full name of the Jenkins job.
        build_number: Specific build number to query. If not provided, the
            latest build is used.

    Returns:
        A dict with build status information including build number, result,
        whether it is still building, timestamp and duration.
    """
    try:
        client = get_client()

        if build_number is None:
            job_info = client.get_job_info(job_name)
            last_build = job_info.get("lastBuild")
            if last_build is None:
                return {
                    "success": True,
                    "job_name": job_name,
                    "message": "No builds found for this job.",
                }
            build_number = last_build["number"]

        build_info = client.get_build_info(job_name, build_number)

        timestamp_ms = build_info.get("timestamp", 0)
        start_time = (
            datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
            if timestamp_ms
            else None
        )

        duration_ms = build_info.get("duration", 0)
        estimated_duration_ms = build_info.get("estimatedDuration", 0)

        return {
            "success": True,
            "job_name": job_name,
            "build_number": build_info.get("number"),
            "result": build_info.get("result"),  # SUCCESS, FAILURE, ABORTED, None (building)
            "building": build_info.get("building", False),
            "start_time": start_time,
            "duration_ms": duration_ms,
            "estimated_duration_ms": estimated_duration_ms,
            "display_name": build_info.get("displayName", ""),
            "url": build_info.get("url", ""),
        }
    except jenkins.JenkinsException as e:
        return _format_error(e)
    except ValueError as e:
        return _format_error(e)


# ---------------------------------------------------------------------------
# Tool 4: get_build_log
# ---------------------------------------------------------------------------
@mcp.tool
def get_build_log(
    job_name: str,
    build_number: int,
    start_line: int = 0,
    max_lines: int = 100,
    from_end: bool = False,
) -> dict[str, Any]:
    """Get paginated console output for a Jenkins build.

    Supports reading from the beginning or the end of the log.

    Args:
        job_name: Full name of the Jenkins job.
        build_number: The build number to fetch logs for.
        start_line: Line offset. When from_end is False, this is the 0-based
            line number to start reading from. When from_end is True, this is
            the number of lines to skip from the very end (0 means start from
            the last line).
        max_lines: Maximum number of lines to return (default 100).
        from_end: If True, read lines from the end of the log instead of the
            beginning.

    Returns:
        A dict with the log content, total line count, the actual start line
        number, and whether more lines are available.
    """
    try:
        client = get_client()
        full_output = client.get_build_console_output(job_name, build_number)
        all_lines = full_output.splitlines()
        total_lines = len(all_lines)

        if from_end:
            # from_end mode: start_line is the offset from the end
            # e.g. start_line=0, max_lines=50 => last 50 lines
            end_idx = total_lines - start_line
            if end_idx < 0:
                end_idx = 0
            begin_idx = max(end_idx - max_lines, 0)
            selected = all_lines[begin_idx:end_idx]
            actual_start = begin_idx
            has_more = begin_idx > 0
        else:
            # Normal forward mode
            begin_idx = min(start_line, total_lines)
            end_idx = min(begin_idx + max_lines, total_lines)
            selected = all_lines[begin_idx:end_idx]
            actual_start = begin_idx
            has_more = end_idx < total_lines

        return {
            "success": True,
            "job_name": job_name,
            "build_number": build_number,
            "log": "\n".join(selected),
            "total_lines": total_lines,
            "start_line": actual_start,
            "lines_returned": len(selected),
            "has_more": has_more,
            "from_end": from_end,
        }
    except jenkins.JenkinsException as e:
        return _format_error(e)
    except ValueError as e:
        return _format_error(e)


# ---------------------------------------------------------------------------
# Tool 5: cancel_build
# ---------------------------------------------------------------------------
@mcp.tool
def cancel_build(job_name: str, build_number: int) -> dict[str, Any]:
    """Cancel (stop) a running Jenkins build.

    Args:
        job_name: Full name of the Jenkins job.
        build_number: The build number to cancel.

    Returns:
        A dict indicating whether the cancellation was successful.
    """
    try:
        client = get_client()
        client.stop_build(job_name, build_number)
        return {
            "success": True,
            "job_name": job_name,
            "build_number": build_number,
            "message": f"Build #{build_number} of '{job_name}' has been cancelled.",
        }
    except jenkins.JenkinsException as e:
        return _format_error(e)
    except ValueError as e:
        return _format_error(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
