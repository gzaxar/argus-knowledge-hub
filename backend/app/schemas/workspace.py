from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


class WorkspaceCreate(BaseModel):
    name: str
    # Left out, it is derived from the name by the installation's rule.
    # Sent, it is used as-is: a convention should be the default, not a
    # cage, and an admin importing an existing identifier needs the exact
    # one they already have.
    id: Optional[str] = None
    # The template packages it starts from, besides core-facility (always): e.g. ["accelerator"].
    packages: list[str] = []
    # With the accelerator catalogue: the catalogue workspace whose shared types it hangs from; left out, the
    # whole catalogue goes in this workspace.
    catalogue_workspace_id: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    is_global: Optional[bool] = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_global: bool
    created_at: datetime


class MyWorkspaceOut(WorkspaceOut):
    can_read: bool
    can_create: bool
    can_modify: bool
    can_delete: bool
    can_read_tickets: bool
    can_create_tickets: bool
    can_modify_tickets: bool
    can_delete_tickets: bool
    can_read_documents: bool
    can_create_documents: bool
    can_modify_documents: bool
    can_delete_documents: bool
    can_approve_documents: bool


class MembershipUpdate(BaseModel):
    email: str
    can_read: bool = True
    can_create: bool = False
    can_modify: bool = False
    can_delete: bool = False
    can_read_tickets: bool = True
    can_create_tickets: bool = False
    can_modify_tickets: bool = False
    can_delete_tickets: bool = False
    can_read_documents: bool = True
    can_create_documents: bool = False
    can_modify_documents: bool = False
    can_delete_documents: bool = False
    can_approve_documents: bool = False


class MembershipOut(BaseModel):
    user_id: str
    email: str
    name: Optional[str]
    can_read: bool
    can_create: bool
    can_modify: bool
    can_delete: bool
    can_read_tickets: bool
    can_create_tickets: bool
    can_modify_tickets: bool
    can_delete_tickets: bool
    can_read_documents: bool
    can_create_documents: bool
    can_modify_documents: bool
    can_delete_documents: bool
    can_approve_documents: bool


class MemberDirectoryOut(BaseModel):
    user_id: str
    email: str
    name: Optional[str]


class MeOut(BaseModel):
    auth_type: Literal["pat", "oidc"]
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    is_admin: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: Optional[str]
    is_admin: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class UserAdminUpdate(BaseModel):
    is_admin: bool


class DefaultAccess(BaseModel):
    default_can_read: bool = False
    default_can_create: bool = False
    default_can_modify: bool = False
    default_can_delete: bool = False
    default_can_read_tickets: bool = False
    default_can_create_tickets: bool = False
    default_can_modify_tickets: bool = False
    default_can_delete_tickets: bool = False
    default_can_read_documents: bool = False
    default_can_create_documents: bool = False
    default_can_modify_documents: bool = False
    default_can_delete_documents: bool = False
    default_can_approve_documents: bool = False


class WorkspaceDetailOut(WorkspaceOut, DefaultAccess):
    pass


class CleanupOptions(BaseModel):
    clear_missing_references: bool = False
    delete_orphaned_objects: bool = False
    remove_dangling_relations: bool = False


class WorkspaceIdRule(BaseModel):
    """How a workspace's identifier is derived from its name."""

    prefix: str = ""
    separator: str = "-"
    case: Literal["lower", "upper", "keep"] = "lower"
    max_length: int = Field(default=40, ge=4, le=120)


class WorkspaceIdSuggestion(BaseModel):
    id: str
    # What the rule produced before a number was added to make it free.
    base: str
    taken: bool


class AssetKeyRule(BaseModel):
    """How keys are made for records created without one."""

    pattern: str
    is_default: bool = False
    example: str = ""
