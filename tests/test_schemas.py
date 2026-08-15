# pylint: disable=missing-module-docstring,missing-function-docstring
import pytest
from pydantic import ValidationError

from schemas import ConnectRepoRequest, DeploymentCreate, ProjectCreate


def test_deploy_create_empty_name_after_strip():
    with pytest.raises(ValidationError):
        DeploymentCreate(platform="vercel", project_name="   ")


def test_deploy_create_name_too_long():
    with pytest.raises(ValidationError):
        DeploymentCreate(platform="vercel", project_name="a" * 64)


def test_deploy_create_repo_url_none_passthrough():
    obj = DeploymentCreate(platform="vercel", project_name="my-app", repo_url=None)
    assert obj.repo_url is None


def test_deploy_create_repo_url_too_few_parts():
    with pytest.raises(ValidationError):
        DeploymentCreate(
            platform="vercel",
            project_name="my-app",
            repo_url="https://github.com/owner",
        )


def test_connect_repo_not_github_url():
    with pytest.raises(ValidationError):
        ConnectRepoRequest(repo_url="https://gitlab.com/owner/repo")


def test_connect_repo_too_few_parts():
    with pytest.raises(ValidationError):
        ConnectRepoRequest(repo_url="https://github.com/owner")


def test_project_create_name_too_long():
    with pytest.raises(ValidationError):
        ProjectCreate(name="x" * 101)
