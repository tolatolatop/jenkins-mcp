"""Jenkins client wrapper with environment-based configuration."""

import os

import jenkins


def get_client() -> jenkins.Jenkins:
    """Create a Jenkins client from environment variables.

    Environment variables:
        JENKINS_URL: Jenkins server URL (required)
        JENKINS_USERNAME: Jenkins username (optional)
        JENKINS_API_TOKEN: Jenkins API token (optional)

    Returns:
        A configured Jenkins client instance.

    Raises:
        ValueError: If JENKINS_URL is not set.
    """
    url = os.environ.get("JENKINS_URL")
    if not url:
        raise ValueError(
            "JENKINS_URL environment variable is required. "
            "Please set it to your Jenkins server URL."
        )
    username = os.environ.get("JENKINS_USERNAME", "")
    token = os.environ.get("JENKINS_API_TOKEN", "")
    return jenkins.Jenkins(url, username=username, password=token)
