from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.import_job import ConfluencePageLink, MergeStrategy
from app.services.import_merge import MERGE_STRATEGIES


class JiraImportConfigParams(BaseModel):
    source: Literal["jira"]
    base_url: str
    jira_schema_id: str
    pat: Optional[str] = None  # omit on update to keep the stored secret


class JiraIssueImportConfigParams(BaseModel):
    source: Literal["jira-issues"]
    base_url: str
    jql: str
    schema_uid: Optional[str] = None
    link_assets: bool = True
    pat: Optional[str] = None  # omit on update to keep the stored secret


class ConfluenceImportConfigParams(ConfluencePageLink):
    source: Literal["confluence"]
    space_key: Optional[str] = None
    cql: Optional[str] = None
    link_assets: bool = True
    pat: Optional[str] = None  # omit on update to keep the stored secret


class DokuwikiImportConfigParams(BaseModel):
    source: Literal["dokuwiki"]
    page_url: str
    include_children: bool = True
    link_assets: bool = True
    pat: Optional[str] = None  # a public wiki: never needed, accepted for the form's sake


class GitImportConfigParams(BaseModel):
    source: Literal["git"]
    provider: Literal["github", "gitlab"]
    repo_url: str
    branch: str = "main"
    pat: Optional[str] = None  # omit on update to keep the stored secret


class Epik8sImportConfigParams(BaseModel):
    """EPIK8s control configuration — one beamline's values.yaml."""

    source: Literal["epik8s"]
    provider: Literal["github", "gitlab"]
    repo_url: str
    branch: str = "main"
    path: str = "deploy/values.yaml"
    create_missing_nodes: bool = True
    # The chain the configuration implies (see Epik8sImportRequest).
    infer_elements: bool = False
    infer_controllers: bool = False
    it_workspace: Optional[str] = None
    link_inventory: bool = False
    ai_unrecognised: bool = False
    pat: Optional[str] = None  # omit on update to keep the stored secret


ImportConfigParams = Union[
    JiraImportConfigParams,
    JiraIssueImportConfigParams,
    ConfluenceImportConfigParams,
    DokuwikiImportConfigParams,
    GitImportConfigParams,
    Epik8sImportConfigParams,
]


class ScheduleIn(BaseModel):
    """When a saved import runs by itself (services/import_schedule.py)."""
    kind: Literal["off", "hours", "daily", "weekly"] = "off"
    every_hours: Optional[int] = Field(default=None, ge=1, le=168)
    time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: Optional[int] = Field(default=None, ge=0, le=6)          # 0 = Monday
    timezone: Optional[str] = Field(default=None, max_length=64)


class ImportConfigCreate(BaseModel):
    name: str
    merge_strategy: MergeStrategy = "override"
    config: ImportConfigParams = Field(discriminator="source")
    schedule: Optional[ScheduleIn] = None


class ImportConfigUpdate(BaseModel):
    name: Optional[str] = None
    merge_strategy: Optional[MergeStrategy] = None
    config: Optional[ImportConfigParams] = Field(default=None, discriminator="source")
    schedule: Optional[ScheduleIn] = None


class ImportConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    workspace_id: str
    name: str
    source: str
    merge_strategy: str
    params: dict
    last_run_at: Optional[datetime]
    last_import_job_uid: Optional[str]
    schedule_kind: str = "off"
    schedule_every_hours: Optional[int] = None
    schedule_time: Optional[str] = None
    schedule_weekday: Optional[int] = None
    schedule_timezone: Optional[str] = None
    next_run_at: Optional[datetime] = None
    running_since: Optional[datetime] = None
    schedule_failures: int = 0
    last_outcome: Optional[str] = None
    last_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


assert set(MergeStrategy.__args__) == set(MERGE_STRATEGIES)
