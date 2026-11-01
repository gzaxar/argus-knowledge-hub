from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SchemaCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uid: str
    name: str
    description: Optional[str] = None
    is_concrete: bool = True
    parent_schema_uid: Optional[str] = None
    attributes: list = []
    metadata_json: dict = Field(default_factory=dict, alias="metadata")
    version: int = 1
    is_global: bool = False
    applies_to: str = "objects"


class SchemaUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = None
    description: Optional[str] = None
    is_concrete: Optional[bool] = None
    parent_schema_uid: Optional[str] = None
    attributes: Optional[list] = None
    metadata_json: Optional[dict] = Field(default=None, alias="metadata")
    version: Optional[int] = None
    is_global: Optional[bool] = None
    applies_to: Optional[str] = None


class SchemaOut(BaseModel):
    # `serialization_alias` only (not `alias`): from_attributes reads the ORM
    # object's `metadata_json` attribute — `Base.metadata` is a reserved
    # SQLAlchemy attribute name, so an `alias="metadata"` here would shadow
    # it and pydantic would validate against the wrong (MetaData) object.
    model_config = ConfigDict(from_attributes=True)

    uid: str
    workspace_id: str
    name: str
    description: Optional[str]
    is_concrete: bool
    parent_schema_uid: Optional[str]
    attributes: list
    metadata_json: dict = Field(serialization_alias="metadata")
    version: int
    icon_uid: Optional[str] = None
    is_global: bool
    applies_to: str
    created_at: datetime
    updated_at: datetime
    # Where it comes from (app/packages/origin.py): a package at a version, an import, or made here. Given by
    # the type list and a type's page.
    origin: Optional[dict] = None
