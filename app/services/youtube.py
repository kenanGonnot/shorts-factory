"""Minimal YouTube uploader using google-api-python-client."""
from __future__ import annotations
from app.core.config import get_settings
from app.core.logging import log


def upload_short(video_path: str, title: str, description: str, tags: list[str]) -> str:
    s = get_settings()
    if not s.youtube_client_secrets_file:
        log.warning("youtube.skipped", reason="no client secrets configured")
        return "dryrun-" + title.lower().replace(" ", "-")[:20]

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_file(s.youtube_token_file)
    yt = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:95],
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {"privacyStatus": s.youtube_privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = req.execute()
    return resp["id"]
