"""Queue current material revisions for the embedding model in the root .env."""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text

from app.credentials import resolve_setting
from app.services.material_embedding_service import enqueue_rebuild


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="enqueue rebuild jobs; without this flag only count candidates")
    args = parser.parse_args()
    database_url = resolve_setting("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL 未配置")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            ids = conn.execute(text(
                "SELECT id FROM materials WHERE deleted_at IS NULL AND usage_status <> 'archived' "
                "AND current_revision_id IS NOT NULL ORDER BY id"
            )).scalars().all()
        if not args.apply:
            print(f"待处理素材：{len(ids)}；使用 --apply 创建任务")
            return
        accepted = reused = failed = 0
        for material_id in ids:
            try:
                with engine.begin() as conn:
                    result = enqueue_rebuild(conn, material_id)
                accepted += 1
                reused += int(result["reused"])
            except Exception:
                failed += 1
                print(f"素材 {material_id} 入队失败，请检查配置和数据库日志")
        print(f"素材数={len(ids)} 已受理={accepted} 复用={reused} 入队失败={failed}")
        if failed:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
