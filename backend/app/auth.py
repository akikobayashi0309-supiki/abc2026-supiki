from dataclasses import dataclass

import firebase_admin
from fastapi import Header, HTTPException, status
from firebase_admin import auth


@dataclass(frozen=True)
class User:
    uid: str
    is_anonymous: bool


def _app() -> firebase_admin.App:
    # Uses Application Default Credentials (the Cloud Run runtime service account).
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()


def get_current_user(authorization: str = Header(default="")) -> User:
    """Verify the Firebase ID token sent as `Authorization: Bearer <token>`."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = auth.verify_id_token(token, app=_app())
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    provider = claims.get("firebase", {}).get("sign_in_provider")
    return User(uid=claims["uid"], is_anonymous=provider == "anonymous")
