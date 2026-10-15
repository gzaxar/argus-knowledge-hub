from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

# "remove_all_before" is retired (services/import_merge.RETIRED_STRATEGIES): a new
# import may not ask for it; a stored configuration that names it runs as override.
MergeStrategy = Literal["override", "no_override", "update_if_newer"]


class JiraImportRequest(BaseModel):
    source: Literal["jira"]
    base_url: str
    pat: str
    jira_schema_id: str
    merge_strategy: MergeStrategy = "override"


class JiraIssueImportRequest(BaseModel):
    """Import from a Jira issue tracker (work), as opposed to Insight
    objects (equipment) — a different API and a different destination."""

    source: Literal["jira-issues"]
    base_url: str
    pat: str
    # Any Jira search query the account can run; a project filter is the usual case.
    jql: str
    # Optional ticket type, giving the imported tickets configurable
    # attributes the same way object types do.
    schema_uid: Optional[str] = None
    # Link a ticket to any asset whose key it mentions.
    link_assets: bool = True
    merge_strategy: MergeStrategy = "override"


class ConfluencePageLink(BaseModel):
    """A link to one page (the short link its Share button gives, or the page's
    address) imports that page and, unless `include_children` is false, the pages
    under it. The server comes from the link when `base_url` is left out."""
    base_url: Optional[str] = None
    page_url: Optional[str] = None
    include_children: bool = True

    @model_validator(mode="after")
    def _a_server_or_a_page(self):
        from app.services.confluence_import import PageLinkError, parse_page_link
        if self.page_url:
            try:
                parse_page_link(self.page_url)
            except PageLinkError as exc:
                raise ValueError(str(exc))
        elif not self.base_url:
            raise ValueError("The Confluence server URL, or a link to a page, is required.")
        return self


class ConfluenceImportRequest(ConfluencePageLink):
    source: Literal["confluence"]
    pat: str
    # One space, or any CQL the account can run. A space is the usual case.
    space_key: Optional[str] = None
    cql: Optional[str] = None
    link_assets: bool = True
    merge_strategy: MergeStrategy = "override"


class GitImportRequest(BaseModel):
    source: Literal["git"]
    provider: Literal["github", "gitlab"]
    repo_url: str
    # Omitted for a public repository: no token is sent at all, rather than
    # an empty one, which these APIs reject outright.
    pat: Optional[str] = None
    branch: str = "main"
    merge_strategy: MergeStrategy = "override"


class Epik8sImportRequest(BaseModel):
    """EPIK8s control configuration: one beamline's values.yaml.

    Read-only by design. The file in git deploys the accelerator; a setpoint
    edited in the hub that never reaches the machine would be worse than not
    holding it at all, so what is imported is stamped with where it came from.
    """

    source: Literal["epik8s"]
    provider: Literal["github", "gitlab"]
    repo_url: str
    pat: Optional[str] = None
    branch: str = "main"
    # Where the beamline's configuration sits in that repository.
    path: str = "deploy/values.yaml"
    # An address no object in the inventory carries becomes an Access Point
    # marked as needing confirmation. Off, and it is only reported.
    create_missing_nodes: bool = True
    # Also make what the channels drive: the pumps, magnets, power supplies, cameras,
    # BPM electronics, LLRF and modulator units the file refers to without listing.
    # They are inferences, marked as such, and need the catalogue's types seeded.
    infer_elements: bool = False
    # Also make the controller box each IOC talks to (an IPCMini, a TPG 366, a Pollux chain), powering
    # what its channels drive.
    infer_controllers: bool = False
    # The site-wide workspace where the converters, servers and consoles the hostnames name are made (with
    # their ports), shared, one per box. Needs create rights there.
    it_workspace: Optional[str] = None
    # A channel whose unit the inventory already holds is linked to it (proposed), not given an inferred twin.
    link_inventory: bool = False
    # Channels no rule recognises: the workspace's AI proposes what they drive, as proposals to review.
    ai_unrecognised: bool = False
    merge_strategy: MergeStrategy = "override"


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    workspace_id: str
    source: str
    status: str
    progress: Optional[str]
    counts: dict
    warnings: list[str]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
