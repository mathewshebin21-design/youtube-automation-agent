"""Gated PRIVATE upload of one approved package. Dry run unless --execute and --confirm match.

  python upload_private.py check   --package packages/short_01-<sha12>
  python upload_private.py upload  --package packages/short_01-<sha12> --execute --confirm <sha12>
  python upload_private.py reconcile --package ... --video-id <id or NONE> --by "Shebin"
  python upload_private.py revoke      (revoke the OAuth token at Google and delete it locally)

Hard rules in code (no flag turns them off):
  privacyStatus=private, selfDeclaredMadeForKids=false, no publishAt, containsSyntheticMedia sent explicitly,
  scope youtube.upload only, signed approval must match the exact file + metadata, every compliance check PASS,
  daily cap (default 2/day, hard max 2, IST calendar day) + duplicate check, and an audit line before and after every attempt.
Credentials: OAuth Desktop client JSON at CUTSCENECITY_CLIENT_SECRETS; token cached at
CUTSCENECITY_STATE_DIR/token.json (chmod 600). Neither is ever inside the repo or printed.
"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import compliance  # noqa: E402
import gatelog  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = pathlib.Path(__file__).parent


PART = "snippet,status,paidProductPlacementDetails"


def _paid(upload):
    v = upload.get("paidProductPlacement")
    if not isinstance(v, bool):
        raise PermissionError("package has no explicit paidProductPlacement (reviewer paid_promotion missing)")
    return v


def build_body(pkg):
    u = pkg["upload"]
    if u.get("privacyStatus") != "private":
        raise PermissionError("package privacyStatus must be private")
    body = {"snippet": {"title": u["title"][:100], "description": u["description"][:5000], "tags": u.get("tags", []),
                        "categoryId": u.get("categoryId", "20")},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": bool(u["containsSyntheticMedia"]), "license": "youtube",
                       "embeddable": True},
            "paidProductPlacementDetails": {"hasPaidProductPlacement": _paid(u)}}
    assert "publishAt" not in body["status"]
    return body


def verify_package(pkg_dir):
    """Returns (pkg, problems). Re-checks everything; never trusts a flag saved in the package."""
    pkg_dir = pathlib.Path(pkg_dir)
    problems = []
    pkg = json.loads((pkg_dir / "package.json").read_text())
    clip = json.loads((pkg_dir / "clip.json").read_text())
    claimed = pkg.get("package_sha256")
    if gatelog.sha256_json({k: v for k, v in pkg.items() if k != "package_sha256"}) != claimed:
        problems.append("package.json was edited after export")
    if gatelog.sha256_file(pkg_dir / "video.mp4") != pkg["file_sha256"]:
        problems.append("video.mp4 is not the approved file")
    try:
        entries = gatelog.verify_review_log(pkg_dir / "review_log.jsonl")
        appr = gatelog.latest_approval(entries, pkg["clip"])
        if not appr or appr["sig"] != pkg["approval"]["sig"] or appr["file_sha256"] != pkg["file_sha256"]:
            problems.append("signed approval does not match this file")
        elif appr["metadata_sha256"] != gatelog.sha256_json(clip.get("metadata", {})):
            problems.append("metadata changed after approval")
        elif appr.get("provenance_sha256") != gatelog.sha256_json(clip.get("provenance", {})):
            problems.append("provenance changed after approval")
        elif appr.get("script_sha256") != compliance._sha((clip.get("commentary_script") or {}).get("text") or ""):
            problems.append("script changed after approval")
        script = (clip.get("commentary_script") or {}).get("text")
        if script and not any(e.get("action") == "script_approve" and e.get("clip") == pkg["clip"]
                              and e.get("script_sha256") == compliance._sha(script) for e in entries):
            problems.append("commentary_script: no signed script approval")
        paid = (clip.get("paid_promotion") or {}).get("value")
        if appr and appr.get("paid_promotion") != paid:
            problems.append("paid_promotion changed after approval")
        if not any(e.get("action") == "paid_promotion" and e.get("clip") == pkg["clip"] and e.get("value") == paid
                   and e.get("file_sha256") == pkg["file_sha256"] for e in entries):
            problems.append("paid_promotion: no signed declaration for this file")
        if pkg["upload"].get("paidProductPlacement") is not (paid == "present") or paid not in compliance.PAID_VALUES:
            problems.append("paidProductPlacement in package does not match the signed paid_promotion")
        if compliance.is_mixed_track(clip):
            so = [e for e in entries if e.get("action") == "signoff" and e.get("check") == "mixed_track_commentary_confirmed"
                  and e.get("clip") == pkg["clip"] and e.get("file_sha256") == pkg["file_sha256"]]
            if so and len((so[-1].get("note") or "").split()) < 5:
                problems.append("mixed_track_commentary_confirmed: signed note must have 5+ words")
            if (clip.get("commentary") or {}).get("commentary_source") != "mixed_track_signed":
                problems.append("commentary_source must be mixed_track_signed for a clip without a mic stem")
        scan = clip.get("overlay_scan") or {}
        if scan.get("file_sha256") != pkg["file_sha256"]:
            problems.append("overlay scan was not run on this exact file")
        signed = {e["check"] for e in entries if e.get("action") == "signoff" and e.get("clip") == pkg["clip"]
                  and e.get("file_sha256") == pkg["file_sha256"]}
        for n in compliance.required_human_checks(clip):
            if n not in signed:
                problems.append(f"{n}: no signed sign-off")
        import edit_gates   # phase 2.7: signed per-clip edit choice + captions_reviewed bound to words.json
        problems += edit_gates.signed_problems(clip, entries, pkg["file_sha256"], pkg_dir / edit_gates.WORDS_PACKAGE_NAME)
        cap = pkg.get("captions")
        if edit_gates.captions_burned(clip.get("render")) and (not cap or cap.get("words_json_sha256") != (clip.get("render") or {}).get("words_json_sha256")):
            problems.append("package captions block does not match the reviewed words.json")
    except PermissionError as e:
        problems.append(str(e))
    pol = json.loads((HERE / "editorial-policy.json").read_text())
    compliance.load_extra_checks(pol)
    import script_checks
    ctx = compliance.build_ctx(pol, HERE)
    ctx["previous_upload"] = script_checks.previous_upload(exclude_package=pkg.get("package_sha256"))
    problems += [f"{k}: {v}" for k, v in compliance.blockers(clip, ctx).items()]
    md = clip.get("metadata", {})
    for key in ("title", "description"):
        if md.get(key) != pkg["upload"].get(key):
            problems.append(f"{key} differs between clip and package")
    problems += gatelog.upload_blockers(pkg, gatelog.effective_daily_cap(os.getenv("CUTSCENECITY_DAILY_CAP"), pol.get("daily_upload_cap")))
    return pkg, problems


def get_service():  # pragma: no cover - real network path, never run in tests
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    secrets = os.getenv("CUTSCENECITY_CLIENT_SECRETS")
    if not secrets or not pathlib.Path(secrets).is_file():
        raise SystemExit("set CUTSCENECITY_CLIENT_SECRETS to your OAuth Desktop client JSON (outside the repo)")
    token = gatelog.state_dir() / "token.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        creds = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES).run_local_server(host="127.0.0.1", port=0)
    token.write_text(creds.to_json())
    os.chmod(token, 0o600)
    return build("youtube", "v3", credentials=creds)


def media_upload(path):  # pragma: no cover
    from googleapiclient.http import MediaFileUpload
    return MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)


def upload(pkg_dir, confirm, youtube=None, media_factory=None):
    pkg_dir = pathlib.Path(pkg_dir)
    pkg, problems = verify_package(pkg_dir)
    if problems:
        raise PermissionError("blocked:\n- " + "\n- ".join(problems))
    if confirm != pkg["package_sha256"][:12]:
        raise PermissionError("--confirm must equal the first 12 characters of package_sha256 (proves you read this package)")
    body = build_body(pkg)
    base = {"package_sha256": pkg["package_sha256"], "file_sha256": pkg["file_sha256"], "clip": pkg["clip"],
            "vod_id": pkg["source"]["vod_id"], "start_ms": pkg["source"]["start_ms"], "end_ms": pkg["source"]["end_ms"],
            "approved_by": pkg["approval"]["by"], "privacyStatus": "private",
            "voice_preset": pkg.get("style", {}).get("voice_preset", ""), "caption_style": pkg.get("style", {}).get("caption_style", "")}
    gatelog.audit(status="ATTEMPT", **base)
    youtube = youtube or get_service()
    media = (media_factory or media_upload)(pkg_dir / "video.mp4")
    try:
        req = youtube.videos().insert(part=PART, body=body, media_body=media)
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
    except Exception as e:  # ambiguous: the video may exist; never auto-retry
        gatelog.audit(status="UNKNOWN_RECONCILE", error=type(e).__name__, **base)
        raise
    vid = resp.get("id")
    privacy = resp.get("status", {}).get("privacyStatus")
    gatelog.audit(status="UPLOADED", video_id=vid, returned_privacy=privacy, **base)
    if privacy != "private":
        raise RuntimeError(f"YouTube returned privacyStatus={privacy}; set it to private in Studio NOW")
    return vid


def reconcile(pkg_dir, video_id, by):
    pkg = json.loads((pathlib.Path(pkg_dir) / "package.json").read_text())
    status = "FAILED" if video_id.upper() == "NONE" else "UPLOADED"
    return gatelog.audit(status=status, package_sha256=pkg["package_sha256"], file_sha256=pkg["file_sha256"],
                         clip=pkg["clip"], vod_id=pkg["source"]["vod_id"], start_ms=pkg["source"]["start_ms"],
                         end_ms=pkg["source"]["end_ms"], video_id=None if status == "FAILED" else video_id,
                         reconciled_by=by)


REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def revoke(opener=None):
    """Revoke the stored OAuth token at Google and delete it locally (YouTube Developer Policies: easy revocation)."""
    import urllib.parse
    import urllib.request
    token_path = gatelog.state_dir() / "token.json"
    if not token_path.exists():
        return "no stored token"
    data = json.loads(token_path.read_text())
    token = data.get("refresh_token") or data.get("token")
    req = urllib.request.Request(REVOKE_URL, data=urllib.parse.urlencode({"token": token}).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        (opener or urllib.request.urlopen)(req, timeout=30)
        result = "revoked at Google"
    except Exception as e:  # still delete locally; user can also revoke at myaccount.google.com/permissions
        result = f"Google revoke call failed ({type(e).__name__}); token deleted locally anyway"
    token_path.unlink()
    gatelog.audit(status="TOKEN_REVOKED", package_sha256="-", result=result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["check", "upload", "reconcile", "revoke"])
    p.add_argument("--package")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm")
    p.add_argument("--video-id")
    p.add_argument("--by")
    a = p.parse_args(argv)
    if a.command == "revoke":
        print(revoke())
        return
    if not a.package:
        raise SystemExit("--package is required")
    if a.command == "reconcile":
        if not a.video_id or not a.by:
            raise SystemExit("--video-id (or NONE) and --by are required")
        print(json.dumps(reconcile(a.package, a.video_id, a.by)))
        return
    pkg, problems = verify_package(a.package)
    print(json.dumps({"package_sha256": pkg["package_sha256"], "confirm_code": pkg["package_sha256"][:12],
                      "request_body": build_body(pkg), "blocking": problems}, indent=2))
    if a.command == "upload":
        if not a.execute:
            print("DRY RUN: nothing sent. Add --execute --confirm <confirm_code> to upload as PRIVATE.")
            return
        vid = upload(a.package, a.confirm)
        print(f"Uploaded PRIVATE video {vid}. Check https://studio.youtube.com/video/{vid}/edit")


if __name__ == "__main__":
    main()
