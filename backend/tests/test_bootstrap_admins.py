"""A new instance has no administrator and nobody to make one in the web app: the emails in
ARGUS_BOOTSTRAP_ADMINS are made administrators when they first sign in, and nobody else is."""
import secrets

from app.auth import _resolve_oidc_user
from app.db import SessionLocal


def test_a_listed_email_is_an_administrator_from_its_first_sign_in(monkeypatch):
    t = secrets.token_hex(4)
    listed, other = f"first-{t}@lnf.infn.it", f"other-{t}@lnf.infn.it"
    monkeypatch.setenv("ARGUS_BOOTSTRAP_ADMINS", f" {listed.upper()} , nobody@example.org")
    db = SessionLocal()
    try:
        assert _resolve_oidc_user(db, {"sub": f"s1-{t}", "email": listed}).is_admin is True
        assert _resolve_oidc_user(db, {"sub": f"s2-{t}", "email": other}).is_admin is False
    finally:
        db.rollback()
        db.close()


def test_without_the_setting_nobody_is(monkeypatch):
    monkeypatch.delenv("ARGUS_BOOTSTRAP_ADMINS", raising=False)
    db = SessionLocal()
    try:
        assert _resolve_oidc_user(db, {"sub": f"s-{secrets.token_hex(4)}", "email": "x@y.org"}).is_admin is False
    finally:
        db.rollback()
        db.close()


def test_parallel_first_requests_resolve_the_same_user(monkeypatch):
    """Force both requests to miss the initial SELECT before either may insert."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import delete, func, select
    from sqlalchemy.orm import Session
    from app.models.user import User

    sub = f"parallel-{secrets.token_hex(8)}"
    claims = {"sub": sub, "email": f"{sub}@argus.test", "name": "Parallel sign-in"}
    barrier = Barrier(2)
    original = Session.scalar
    monkeypatch.setenv("ARGUS_BOOTSTRAP_ADMINS", claims["email"])

    def both_read_before_insert(db, statement, *args, **kwargs):
        result = original(db, statement, *args, **kwargs)
        if result is None and "WHERE users.oidc_sub =" in str(statement) and sub in statement.compile().params.values():
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(Session, "scalar", both_read_before_insert)

    def sign_in():
        with SessionLocal() as db:
            user = _resolve_oidc_user(db, claims)
            db.commit()
            return user.id, user.is_admin

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(sign_in) for _ in range(2)]
            identities = [future.result(timeout=20) for future in futures]
        assert identities[0] == identities[1]
        assert identities[0][1] is True
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(User).where(User.oidc_sub == sub)) == 1
            # Both transactions remained usable, including a subsequent resolution.
            assert _resolve_oidc_user(db, claims).id == identities[0][0]
    finally:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.oidc_sub == sub))
            db.commit()
