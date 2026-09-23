"""Load the DVC-built knowledge base into a deployment (the kb-loader container).

Copies `kb/index` into the ChromaDB server's data volume, the documents into
the shared document volume, and the document rows into SQLite - but only when
the version in `kb/manifest.json` differs from the one already loaded, so a
redeploy of unchanged code never touches the live index.

It must run while ChromaDB is stopped (compose orders it before chroma; the
deploy script stops chroma first when the knowledge base changed). Documents
uploaded through the UI live in the same "default" collection and are replaced
when a new knowledge-base version is loaded - see DECISIONS.md.

Usage (inside the container):
    python -m kb.load_kb --kb /kb --chroma-dir /chroma-data --docs-dir /app/storage/documents
"""

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
import sys

PATIENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PATIENT_DIR)

MARKER = ".kb_version"


def _copy_tree_contents(src: str, dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(dst):
        if name == MARKER:
            continue
        path = os.path.join(dst, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def load_records(records_path: str) -> int:
    from api_gateway.app.db import get_db_connection, init_db

    init_db()
    with open(records_path, "r", encoding="utf-8") as fh:
        records = json.load(fh)
    conn = get_db_connection()
    cur = conn.cursor()
    for doc in records["documents"]:
        cur.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc["doc_id"],))
        cur.execute("DELETE FROM documents WHERE doc_id = ?", (doc["doc_id"],))
        cur.execute(
            "INSERT INTO documents (doc_id, filename, file_path, file_size, status, pages, "
            "chunks_count, collection_name, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (doc["doc_id"], doc["filename"], doc["file_path"], doc["file_size"], doc["status"],
             doc["pages"], doc["chunks_count"], doc["collection_name"], doc["created_at"]))
    for c in records["chunks"]:
        cur.execute(
            "INSERT OR REPLACE INTO document_chunks (chunk_id, doc_id, chunk_index, page_number, "
            "text, token_count, embedding_dim, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (c["chunk_id"], c["doc_id"], c["chunk_index"], c["page_number"], c["text"],
             c["token_count"], c["embedding_dim"], c["created_at"]))
    conn.commit()
    conn.close()
    return len(records["documents"])


def _hand_back(paths, uid: int, gid: int) -> None:
    """kb-loader runs as root because the ChromaDB volume is root-owned; the
    SQLite database and documents it writes belong to the services' user."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    for top in paths:
        if not os.path.exists(top):
            continue
        os.chown(top, uid, gid)
        for dirpath, dirnames, filenames in os.walk(top):
            for name in dirnames + filenames:
                os.chown(os.path.join(dirpath, name), uid, gid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True, help="the kb/ directory built by build_kb.py")
    ap.add_argument("--chroma-dir", required=True)
    ap.add_argument("--docs-dir", required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--log", default=os.environ.get("KB_LOAD_LOG", ""),
                    help="append a JSON record of every load here (the data-change log)")
    ap.add_argument("--owner", default="10001:10001", help="uid:gid that owns the app data and documents")
    args = ap.parse_args()

    manifest_path = os.path.join(args.kb, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"[kb-loader] no manifest at {manifest_path}; run `dvc pull` or `dvc repro build_kb` first",
              file=sys.stderr)
        return 1
    with open(manifest_path, "r", encoding="utf-8") as fh:
        version = json.load(fh)["kb_version"]

    marker = os.path.join(args.chroma_dir, MARKER)
    current = open(marker).read().strip() if os.path.exists(marker) else None
    from api_gateway.app.db import DB_PATH

    uid, gid = (int(x) for x in args.owner.split(":"))
    if current == version and not args.force:
        _hand_back([os.path.dirname(DB_PATH), args.docs_dir], uid, gid)
        print(json.dumps({"kb_loader": "unchanged", "kb_version": version}))
        return 0

    _copy_tree_contents(os.path.join(args.kb, "index"), args.chroma_dir)
    os.makedirs(args.docs_dir, exist_ok=True)
    for name in os.listdir(os.path.join(args.kb, "documents")):
        shutil.copy2(os.path.join(args.kb, "documents", name), os.path.join(args.docs_dir, name))
    docs = load_records(os.path.join(args.kb, "records.json"))
    with open(marker, "w") as fh:
        fh.write(version)
    _hand_back([os.path.dirname(DB_PATH), args.docs_dir], uid, gid)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
              "kb_version": version, "previous": current, "documents": docs,
              "collections": manifest.get("collections"), "embedding_model": manifest.get("embedding_model")}
    if args.log:
        # Like the deploy log, but for data: which knowledge base became live, when.
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
        with open(args.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    print(json.dumps({"kb_loader": "loaded", **record}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
