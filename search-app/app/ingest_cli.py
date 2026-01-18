from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple

from .config import settings
from .db import init_db
from .store import ensure_dirs, save_upload, ingest_file_path
from .users import get_user_by_email, create_user, ensure_default_space


def iter_files(paths: List[Path]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for root, _dirs, files in os.walk(p):
                for f in files:
                    out.append(Path(root) / f)
    return out


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpacesAI ingestion CLI: ingest local files into a user's Space")
    parser.add_argument("paths", nargs="+", help="File or directory paths to ingest")
    parser.add_argument("--email", required=True, help="User email to attribute documents to (created if missing)")
    parser.add_argument("--password", default=None, help="Password to use if creating the user (random if omitted)")
    parser.add_argument("--space-id", type=int, default=None, help="Space ID to ingest into (defaults to user's default space)")
    args = parser.parse_args(argv)

    ensure_dirs()
    try:
        init_db()
    except Exception as e:
        print(f"[WARN] init_db failed or skipped: {e}")

    email = args.email.strip().lower()
    user = get_user_by_email(email)
    if not user:
        pwd = args.password or os.urandom(12).hex()
        u = create_user(email, pwd)
        print(f"[INFO] Created user {email} with id={u['id']}")
        user = get_user_by_email(email)
    assert user is not None
    uid = int(user["id"]) if isinstance(user.get("id"), int) else int(user["id"])  # type: ignore

    sid = args.space_id
    if sid is None:
        sid = ensure_default_space(uid)

    # Collect files
    paths = [Path(p).resolve() for p in args.paths]
    files = iter_files(paths)
    if not files:
        print("[ERROR] No files found to ingest", file=sys.stderr)
        return 1

    # Ingest
    ok = 0
    fail = 0
    for p in files:
        try:
            with open(p, "rb") as f:
                data = f.read()
            local_path, oci_url = save_upload(data, p.name, user_email=email)
            meta = {"filename": p.name}
            if oci_url:
                meta["object_url"] = oci_url
            res = ingest_file_path(local_path, user_id=uid, space_id=sid, title=p.stem, metadata=meta)
            print(f"[OK] {p} -> doc_id={res.document_id} chunks={res.num_chunks}")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {p}: {e}", file=sys.stderr)
            fail += 1
    print(f"[DONE] success={ok} failed={fail} user_id={uid} space_id={sid}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
