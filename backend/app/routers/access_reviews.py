"""Role templates and access reviews (asset-model-revision §19 item 1)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_identity, require_permission
from app.db import get_db
from app.models.access_review import AccessReview
from app.routers.ledger import actor_of
from app.services import access_review

router = APIRouter(prefix="/v1/access-reviews", tags=["access reviews"])


@router.get("/templates")
def templates(workspace_id: str = Depends(require_permission("read")), db: Session = Depends(get_db)):
    return [{"id": f"argus-{k}", "name": n, "description": d, "permissions": p, "package": pkg}
            for k, (n, d, p, pkg) in access_review.all_templates(db, workspace_id).items()]


@router.post("/templates")
def install_templates(workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    added = access_review.install_templates(db, workspace_id)
    db.commit()
    return {"added": added}


class CreateIn(BaseModel):
    required_signers: int = 2


@router.post("", status_code=201)
def create_review(body: CreateIn, identity=Depends(get_identity),
                  workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    review = access_review.create(db, workspace_id, actor_of(identity), body.required_signers)
    db.commit()
    return access_review.view(review)


@router.get("")
def list_reviews(workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    return [access_review.view(r, full=False) for r in db.scalars(
        select(AccessReview).where(AccessReview.workspace_id == workspace_id).order_by(AccessReview.created_at.desc()))]


@router.get("/{review_id}")
def get_review(review_id: str, workspace_id: str = Depends(require_permission("approve")),
               db: Session = Depends(get_db)):
    review = db.get(AccessReview, review_id)
    if review is None or review.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Review not found")
    return access_review.view(review)


class SignIn(BaseModel):
    signer: Optional[str] = None      # an API token names the person signing
    comment: Optional[str] = None


@router.post("/{review_id}/sign")
def sign_review(review_id: str, body: SignIn, identity=Depends(get_identity),
                workspace_id: str = Depends(require_permission("approve")), db: Session = Depends(get_db)):
    review = db.get(AccessReview, review_id)
    if review is None or review.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Review not found")
    from app.auth import OidcIdentity
    signer = actor_of(identity) if isinstance(identity, OidcIdentity) else body.signer
    if not signer:
        raise HTTPException(status_code=422, detail="name the signer")
    try:
        access_review.sign(db, review, signer, body.comment)
    except access_review.ReviewError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)})
    db.commit()
    return access_review.view(review)
