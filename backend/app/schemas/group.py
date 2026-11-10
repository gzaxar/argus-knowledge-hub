from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    dn: Optional[str] = None
    name: str
    description: Optional[str] = None
    email: Optional[str] = None
    source: str
    active: bool
    member_count: int = 0
    # The workspaces where it holds a role: who changes its members changes access there.
    workspaces: list[str] = []
    # Owned by this site (null: the installation), and the sites where it holds a role site-wide (issue #26).
    home_site_id: Optional[str] = None
    site_grants: list[dict] = []


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    # A site-owned group: made by an administrator of that site (or of the installation).
    home_site_id: Optional[str] = None


class GroupHomeIn(BaseModel):
    # The site it is to belong to; null: the installation.
    home_site_id: Optional[str] = None
    # false: only the preview, nothing changes.
    confirm: bool = False


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None


class GroupMembersIn(BaseModel):
    emails: str
    send_email: bool = True
    message: Optional[str] = None


class GroupMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    name: Optional[str] = None
    username: Optional[str] = None
    active: bool
    source: str


class GroupAdministratorOut(BaseModel):
    user_id: str
    email: str
    name: Optional[str] = None


class GroupAdministratorIn(BaseModel):
    email: str


class DirectoryStatusOut(BaseModel):
    provider: str
    is_test_data: bool
    groups: int
    active_groups: int
    users: int
    last_synced_at: Optional[datetime] = None
