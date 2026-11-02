from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PortIn(BaseModel):
    """A port made with the record — a network port, or a serial port with its settings: `port of` it
    (services/network_companions)."""
    port_label: str = "eth0"
    port_kind: Optional[str] = "RJ45"
    mac: Optional[str] = None
    link_speed: Optional[str] = None
    port_role: Optional[str] = None
    tcp_port: Optional[int] = None
    operating_mode: Optional[str] = None
    baud: Optional[int] = None
    framing: Optional[str] = None
    flow_control: Optional[str] = None
    port_settings: Optional[str] = None


class AddressIn(BaseModel):
    """A registered address made with the record: the record is `described by` it."""
    ip: Optional[str] = None
    hostname: Optional[str] = None


class AssetCreate(BaseModel):
    uid: str
    schema_uid: str
    # Blank: the workspace's key pattern makes one (services/asset_keys.py).
    key: Optional[str] = None
    name: str
    # Always the type's name; accepted for older clients and ignored.
    type: Optional[str] = None
    avatar_icon_uid: Optional[str] = None
    attributes: dict = {}
    inbound_relations: list[str] = []
    outbound_relations: list[str] = []
    is_global: bool = False
    # Made with it, in the same transaction: its network ports and addresses.
    ports: list[PortIn] = []
    addresses: list[AddressIn] = []


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    # A record whose type cannot be used in its workspace (a type of the workspace it was moved from) is given
    # one of this workspace's here; any other change of type is a type migration.
    schema_uid: Optional[str] = None
    avatar_icon_uid: Optional[str] = None
    attributes: Optional[dict] = None
    inbound_relations: Optional[list[str]] = None
    outbound_relations: Optional[list[str]] = None
    deleted_at: Optional[datetime] = None
    is_global: Optional[bool] = None


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    workspace_id: str
    schema_uid: str
    key: str
    name: str
    type: str
    avatar_icon_uid: Optional[str]
    attributes: dict
    inbound_relations: list[str]
    outbound_relations: list[str]
    is_global: bool
    # Provisional, Active, Retired or Merged: projected by the fact ledger.
    record_status: str = "Active"
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    # The record version (the latest ledger event that touched it), on single-record reads; send it
    # back as If-Match with an edit (flutter-app-design §3.3).
    version: Optional[int] = None


class BulkDeleteRequest(BaseModel):
    uids: list[str]


class BulkDeleteResult(BaseModel):
    deleted: int
    not_found: list[str]


class RelationCreate(BaseModel):
    from_asset_uid: str
    to_asset_uid: str
    relation_type: str


class RelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: str
    from_asset_uid: str
    to_asset_uid: str
    relation_type: str
    created_at: datetime
    # None for hand-made and legacy edges; "ledger" or "derived" for edges the
    # fact ledger maintains, which are not edited directly.
    derivation: Optional[str] = None


class NextKeyOut(BaseModel):
    key: str
    pattern: str
