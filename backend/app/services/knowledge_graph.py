"""One graph over everything the hub knows.

The pieces already are a graph — objects relate to objects, tickets
affect objects and each other, documents describe objects and record
work, people belong to services. What was missing is a way to walk it
without knowing which table each edge lives in.

That is what ARGUS needs. "This camera is down: what else does it depend
on, what broke it before, which procedure covers it, who is responsible"
is one traversal from one node, and answering it by querying five tables
in the right order is the caller's problem only until it is written once
here.

Nodes are identified by (kind, uid) across the whole workspace. Edges are
undirected for traversal — a question about a magnet must find the ticket
that names it, not only the other way — but each edge remembers its own
direction so the answer can still say which way round it is.
"""
import hashlib
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.models.asset_subresources import AssetTicket
from app.models.document import Document, DocumentRelation
from app.models.group import Group, GroupMember
from app.models.issue import Issue, IssueLink
from app.models.schema import Schema
from app.models.user import User
from app.services.visibility import can_see, live_assets_clause, visible_assets_clause, visible_issues_clause

NodeKind = Literal["asset", "ticket", "document", "group", "person", "type"]

MAX_NODES = 400


@dataclass(frozen=True)
class NodeRef:
    kind: str
    uid: str


@dataclass
class Node:
    kind: str
    uid: str
    label: str
    sublabel: Optional[str] = None
    type_name: Optional[str] = None
    state: Optional[str] = None
    # How many hops from the node the traversal started at.
    depth: int = 0
    # A restricted record the viewer may not see (I-ACL-1): drawn so the
    # structure is honest, but with no name, type or real uid, and never
    # expanded.
    restricted: bool = False


@dataclass
class Edge:
    from_kind: str
    from_uid: str
    to_kind: str
    to_uid: str
    relation: str
    # What sort of connection this is, so a caller can weigh them: an
    # object's own structure is not the same kind of fact as a ticket that
    # happened to mention it.
    via: str


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    truncated: bool = False


def _ticket_key(issue: Issue) -> str:
    return (issue.attributes or {}).get("argus_source_key") or issue.uid


def _label_asset(asset: Asset) -> Node:
    return Node(kind="asset", uid=asset.uid, label=asset.name, sublabel=asset.key,
                type_name=asset.type)


def _label_issue(issue: Issue) -> Node:
    return Node(kind="ticket", uid=issue.uid, label=issue.title,
                sublabel=(issue.attributes or {}).get("argus_source_key"),
                state=issue.state)


def _label_document(document: Document) -> Node:
    return Node(kind="document", uid=document.uid, label=document.title,
                sublabel=document.code)


def _label_group(group: Group) -> Node:
    return Node(kind="group", uid=group.uid, label=group.name, sublabel=group.dn)


def _label_person(user: User) -> Node:
    return Node(kind="person", uid=user.id, label=user.name or user.email,
                sublabel=user.email)


def ticket_uids_by_key(db: Session, workspace_id: str) -> dict[str, list[str]]:
    """ticket key -> the tickets holding it. Built once per traversal: doing
    it per node turned a walk over a few objects into a scan of every
    ticket in the workspace, several hundred times over."""
    out: dict[str, list[str]] = {}
    for issue in db.scalars(select(Issue).where(Issue.workspace_id == workspace_id)):
        out.setdefault(_ticket_key(issue), []).append(issue.uid)
    return out


def _neighbours_of_asset(db: Session, workspace_id: str, uid: str,
                         ctx: Optional[dict] = None) -> list[tuple[Edge, NodeRef]]:
    out: list[tuple[Edge, NodeRef]] = []

    for relation in db.scalars(
        select(Relation).where(
            (Relation.from_asset_uid == uid) | (Relation.to_asset_uid == uid)
        )
    ):
        outgoing = relation.from_asset_uid == uid
        other = relation.to_asset_uid if outgoing else relation.from_asset_uid
        out.append((
            Edge(from_kind="asset", from_uid=relation.from_asset_uid,
                 to_kind="asset", to_uid=relation.to_asset_uid,
                 relation=relation.relation_type, via="structure"),
            NodeRef("asset", other),
        ))

    # Tickets reach objects by key, not uid — the link table predates local
    # tickets and still carries rows for keys imported from elsewhere.
    by_key = (ctx or {}).get("ticket_uids_by_key")
    if by_key is None:
        by_key = ticket_uids_by_key(db, workspace_id)
    ticket_uids: set[str] = set()
    for row in db.scalars(select(AssetTicket).where(AssetTicket.asset_uid == uid)):
        ticket_uids.update(by_key.get(row.ticket_key, ()))
    for issue_uid in db.scalars(
        select(Issue.uid).where(Issue.workspace_id == workspace_id, Issue.asset_uid == uid)
    ):
        ticket_uids.add(issue_uid)
    for issue_uid in ticket_uids:
        out.append((
            Edge(from_kind="ticket", from_uid=issue_uid, to_kind="asset", to_uid=uid,
                 relation="affects", via="work"),
            NodeRef("ticket", issue_uid),
        ))

    for relation in db.scalars(
        select(DocumentRelation).where(
            DocumentRelation.workspace_id == workspace_id,
            DocumentRelation.to_type == "asset",
            DocumentRelation.to_uid == uid,
        )
    ):
        out.append((
            Edge(from_kind="document", from_uid=relation.from_document_uid,
                 to_kind="asset", to_uid=uid,
                 relation=relation.relation_type, via="documentation"),
            NodeRef("document", relation.from_document_uid),
        ))

    return out


def _neighbours_of_ticket(db: Session, workspace_id: str, uid: str,
                          ctx: Optional[dict] = None) -> list[tuple[Edge, NodeRef]]:
    out: list[tuple[Edge, NodeRef]] = []
    issue = db.get(Issue, uid)
    if issue is None:
        return out

    key = _ticket_key(issue)
    asset_uids = {
        row.asset_uid
        for row in db.scalars(select(AssetTicket).where(AssetTicket.ticket_key == key))
    }
    if issue.asset_uid:
        asset_uids.add(issue.asset_uid)
    for asset_uid in asset_uids:
        out.append((
            Edge(from_kind="ticket", from_uid=uid, to_kind="asset", to_uid=asset_uid,
                 relation="affects", via="work"),
            NodeRef("asset", asset_uid),
        ))

    for link in db.scalars(
        select(IssueLink).where(
            (IssueLink.from_issue_uid == uid) | (IssueLink.to_issue_uid == uid)
        )
    ):
        other = link.to_issue_uid if link.from_issue_uid == uid else link.from_issue_uid
        out.append((
            Edge(from_kind="ticket", from_uid=link.from_issue_uid,
                 to_kind="ticket", to_uid=link.to_issue_uid,
                 relation=link.relation_type, via="work"),
            NodeRef("ticket", other),
        ))

    for relation in db.scalars(
        select(DocumentRelation).where(
            DocumentRelation.workspace_id == workspace_id,
            DocumentRelation.to_type == "issue",
            DocumentRelation.to_uid == uid,
        )
    ):
        out.append((
            Edge(from_kind="document", from_uid=relation.from_document_uid,
                 to_kind="ticket", to_uid=uid,
                 relation=relation.relation_type, via="documentation"),
            NodeRef("document", relation.from_document_uid),
        ))

    return out


def _neighbours_of_document(db: Session, workspace_id: str, uid: str,
                            ctx: Optional[dict] = None) -> list[tuple[Edge, NodeRef]]:
    out: list[tuple[Edge, NodeRef]] = []
    kind_by_to_type = {"asset": "asset", "issue": "ticket", "document": "document"}

    for relation in db.scalars(
        select(DocumentRelation).where(
            DocumentRelation.workspace_id == workspace_id,
            DocumentRelation.from_document_uid == uid,
        )
    ):
        kind = kind_by_to_type.get(relation.to_type)
        if kind is None:
            continue
        out.append((
            Edge(from_kind="document", from_uid=uid, to_kind=kind, to_uid=relation.to_uid,
                 relation=relation.relation_type, via="documentation"),
            NodeRef(kind, relation.to_uid),
        ))

    for relation in db.scalars(
        select(DocumentRelation).where(
            DocumentRelation.workspace_id == workspace_id,
            DocumentRelation.to_type == "document",
            DocumentRelation.to_uid == uid,
        )
    ):
        out.append((
            Edge(from_kind="document", from_uid=relation.from_document_uid,
                 to_kind="document", to_uid=uid,
                 relation=relation.relation_type, via="documentation"),
            NodeRef("document", relation.from_document_uid),
        ))

    return out


def _neighbours_of_group(db: Session, workspace_id: str, uid: str,
                         ctx: Optional[dict] = None) -> list[tuple[Edge, NodeRef]]:
    return [
        (
            Edge(from_kind="person", from_uid=member.user_id, to_kind="group", to_uid=uid,
                 relation="member of", via="people"),
            NodeRef("person", member.user_id),
        )
        for member in db.scalars(select(GroupMember).where(GroupMember.group_uid == uid))
    ]


def _neighbours_of_person(db: Session, workspace_id: str, uid: str,
                          ctx: Optional[dict] = None) -> list[tuple[Edge, NodeRef]]:
    return [
        (
            Edge(from_kind="person", from_uid=uid, to_kind="group", to_uid=member.group_uid,
                 relation="member of", via="people"),
            NodeRef("group", member.group_uid),
        )
        for member in db.scalars(select(GroupMember).where(GroupMember.user_id == uid))
    ]


_NEIGHBOURS = {
    "asset": _neighbours_of_asset,
    "ticket": _neighbours_of_ticket,
    "document": _neighbours_of_document,
    "group": _neighbours_of_group,
    "person": _neighbours_of_person,
}


def _anonymous(kind: str, uid: str) -> Node:
    opaque = "restricted-" + hashlib.sha256(f"{kind}:{uid}".encode()).hexdigest()[:12]
    return Node(kind=kind, uid=opaque, label="Restricted record", restricted=True)


def _asset_visible(db: Session, asset: Asset, workspace_id: str) -> bool:
    """The same rule the REST API applies (routers/assets._get_visible_asset).

    It has to be the same rule, or a global model is referenced everywhere
    and then vanishes from the one view built to show what connects to what
    — which is where an installation with a shared model layer needs it most.
    """
    return asset.workspace_id == workspace_id or bool(asset.is_global)


def load_node(db: Session, workspace_id: str, kind: str, uid: str) -> Optional[Node]:
    """The node itself, or None when it doesn't exist or isn't this
    workspace's to see."""
    if kind == "asset":
        asset = db.get(Asset, uid)
        if not (asset and _asset_visible(db, asset, workspace_id)):
            return None
        return _label_asset(asset) if can_see(asset) else _anonymous(kind, uid)
    if kind == "ticket":
        issue = db.get(Issue, uid)
        if not (issue and issue.workspace_id == workspace_id):
            return None
        return _label_issue(issue) if can_see(issue) else _anonymous(kind, uid)
    if kind == "document":
        document = db.get(Document, uid)
        visible = document is not None and (
            document.workspace_id == workspace_id or document.is_global
        )
        return _label_document(document) if visible else None
    if kind == "group":
        group = db.get(Group, uid)
        return _label_group(group) if group else None
    if kind == "person":
        user = db.get(User, uid)
        return _label_person(user) if user else None
    return None


def traverse(
    db: Session,
    workspace_id: str,
    kind: str,
    uid: str,
    depth: int = 1,
    kinds: Optional[Iterable[str]] = None,
    max_nodes: int = MAX_NODES,
) -> Graph:
    """Everything within `depth` hops of one node.

    Breadth-first and capped: a hub object in a real inventory reaches most
    of the graph in three hops, and returning that is useless to a reader
    and expensive for everyone. When the cap bites, the graph says so
    rather than pretending it is complete.
    """
    start = load_node(db, workspace_id, kind, uid)
    if start is None or start.restricted:
        return Graph()

    wanted = set(kinds) if kinds else None
    graph = Graph(nodes=[start])
    seen_nodes = {NodeRef(kind, uid)}
    seen_edges: set[tuple] = set()

    # Built once and shared by every node the walk touches.
    ctx = {"ticket_uids_by_key": ticket_uids_by_key(db, workspace_id)}

    anonymous: dict[NodeRef, str] = {}
    frontier = [NodeRef(kind, uid)]
    for hop in range(1, max(depth, 0) + 1):
        next_frontier: list[NodeRef] = []
        for ref in frontier:
            expand = _NEIGHBOURS.get(ref.kind)
            if expand is None:
                continue
            for edge, neighbour in expand(db, workspace_id, ref.uid, ctx):
                if wanted is not None and neighbour.kind not in wanted:
                    continue

                # Resolve before drawing. Relations are not filtered by
                # workspace when they are collected, so a link to another
                # workspace's private object would otherwise be drawn as an
                # edge to nothing — naming a uid the caller may not see, and
                # rendering as a line into empty space.
                known = neighbour in seen_nodes
                node = None if known else load_node(
                    db, workspace_id, neighbour.kind, neighbour.uid
                )
                if not known and node is None:
                    continue
                if node is not None and node.restricted or anonymous.get(neighbour):
                    # Point the edge at the opaque id, never the real one.
                    anonymous[neighbour] = node.uid if node is not None else anonymous[neighbour]
                    edge = replace(edge, **({"to_uid": anonymous[neighbour]} if edge.to_uid == neighbour.uid
                                            else {"from_uid": anonymous[neighbour]}))

                signature = (
                    edge.from_kind, edge.from_uid, edge.to_kind, edge.to_uid,
                    edge.relation, edge.via,
                )
                if signature not in seen_edges:
                    seen_edges.add(signature)
                    graph.edges.append(edge)
                if known:
                    continue
                if len(graph.nodes) >= max_nodes:
                    graph.truncated = True
                    return graph
                node.depth = hop
                seen_nodes.add(neighbour)
                graph.nodes.append(node)
                if not node.restricted:
                    next_frontier.append(neighbour)
        frontier = next_frontier
        if not frontier:
            break

    return graph


def graph_summary(db: Session, workspace_id: str) -> dict:
    """How much of a graph this workspace actually has.

    Useful on its own — a knowledge graph with no edges between objects and
    documentation is a filing cabinet, and the number says which it is.
    """
    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    assets = count(Asset, Asset.workspace_id == workspace_id, visible_assets_clause(workspace_id),
                   Asset.deleted_at.is_(None), live_assets_clause())
    tickets = count(Issue, Issue.workspace_id == workspace_id, visible_issues_clause())
    documents = count(Document, Document.workspace_id == workspace_id)
    types = count(Schema, Schema.workspace_id == workspace_id)
    groups = count(Group)

    asset_edges = count(Relation, Relation.workspace_id == workspace_id)
    document_edges = count(DocumentRelation, DocumentRelation.workspace_id == workspace_id)
    ticket_edges = db.scalar(
        select(func.count())
        .select_from(IssueLink)
        .join(Issue, Issue.uid == IssueLink.from_issue_uid)
        .where(Issue.workspace_id == workspace_id)
    ) or 0
    # A ticket reaches an object two ways — the subject field on the ticket
    # itself, and a link row carrying a ticket *key* — and the traversal
    # walks both. Counting only one of them reports zero on a workspace
    # where every ticket names its object directly, which is exactly the
    # wrong answer to the question this number exists to answer.
    ticket_asset_pairs: set[tuple[str, str]] = set()
    for issue_uid, asset_uid in db.execute(
        select(Issue.uid, Issue.asset_uid).where(
            Issue.workspace_id == workspace_id, Issue.asset_uid.is_not(None)
        )
    ):
        ticket_asset_pairs.add((issue_uid, asset_uid))

    by_key = ticket_uids_by_key(db, workspace_id)
    for asset_uid, ticket_key in db.execute(
        select(AssetTicket.asset_uid, AssetTicket.ticket_key)
        .join(Asset, Asset.uid == AssetTicket.asset_uid)
        .where(Asset.workspace_id == workspace_id)
    ):
        for issue_uid in by_key.get(ticket_key, ()):
            ticket_asset_pairs.add((issue_uid, asset_uid))
    ticket_asset_edges = len(ticket_asset_pairs)

    return {
        "nodes": {
            "assets": assets, "tickets": tickets, "documents": documents,
            "types": types, "groups": groups,
        },
        "edges": {
            "asset_to_asset": asset_edges,
            "ticket_to_asset": ticket_asset_edges,
            "ticket_to_ticket": ticket_edges,
            "document_to_anything": document_edges,
        },
    }
