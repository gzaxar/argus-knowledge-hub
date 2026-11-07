from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    permissions: dict
    is_system: bool
    rank: int


class RoleBindingCreate(BaseModel):
    subject_type: Literal["user", "group"]
    subject_id: str
    role_id: str


class InvitationIn(BaseModel):
    # One or more addresses, as pasted: separated by commas, semicolons or new lines; `Name <address>` is fine.
    emails: str
    role_id: Optional[str] = None
    send_email: bool = True
    message: Optional[str] = None
    # Into a group instead: an existing one, or a new local one by this name. The role then goes to the group.
    group_uid: Optional[str] = None
    new_group: Optional[str] = None


class InvitedPerson(BaseModel):
    email: str
    user_id: str
    added: bool             # not known before: added now, waiting for the first sign-in
    granted: bool           # False: already had this role here (or, into a group, already in it)
    joined: bool = False    # into a group: added to it now
    signed_in: bool
    emailed: bool
    error: Optional[str] = None


class InvitationOut(BaseModel):
    workspace_id: str
    role_id: Optional[str] = None
    role_name: Optional[str] = None
    group_uid: Optional[str] = None
    group_name: Optional[str] = None
    group_granted: bool = False
    people: list[InvitedPerson]
    not_addresses: list[str]


class RoleBindingOut(BaseModel):
    id: int
    workspace_id: str
    subject_type: str
    subject_id: str
    # Resolved for display, so a list of bindings doesn't need a second
    # round trip per row to say who it's about.
    subject_label: str
    subject_active: bool
    # A person added by e-mail who has not signed in yet: the access waits for them.
    subject_pending: bool = False
    role_id: str
    role_name: str
    created_at: Optional[datetime] = None


class EffectivePermissionsOut(BaseModel):
    workspace_id: str
    is_admin: bool
    objects: list[str]
    tickets: list[str]
    documents: list[str]
    workspace: list[str]
