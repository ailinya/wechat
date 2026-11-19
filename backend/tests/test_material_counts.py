"""The derived count must follow committed material changes exactly."""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.repositories.material_repository import list_materials


def assert_count(conn, expected):
    assert conn.execute(text('SELECT active_count FROM material_counts WHERE singleton')).scalar_one() == expected
    assert conn.execute(text('SELECT count(*) FROM materials WHERE deleted_at IS NULL')).scalar_one() == expected


def test_count_tracks_bulk_changes_and_rollback(db_engine):
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO materials(title) SELECT 'bulk-' || i FROM generate_series(1, 6) i"))
        conn.execute(text("UPDATE materials SET deleted_at=now() WHERE title IN ('bulk-1','bulk-2')"))
        assert_count(conn, 4)
        conn.execute(text("UPDATE materials SET deleted_at=NULL WHERE title='bulk-1'"))
        conn.execute(text("DELETE FROM materials WHERE title IN ('bulk-2','bulk-3')"))
        assert_count(conn, 4)
        _, total = list_materials(conn, 1, 10, usage_status=None, category_id=None, tag_id=None, keyword=None)
        _, filtered = list_materials(conn, 1, 10, usage_status=None, category_id=None, tag_id=None, keyword='bulk-1')
        assert (total, filtered) == (4, 1)
    with db_engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("INSERT INTO materials(title) VALUES ('rollback')"))
        assert_count(conn, 5)
        tx.rollback()
    with db_engine.connect() as conn:
        assert_count(conn, 4)
        conn.commit()
        tx = conn.begin()
        conn.execute(text('TRUNCATE materials CASCADE'))
        assert_count(conn, 0)
        tx.rollback()
        assert_count(conn, 4)


def test_count_tracks_concurrent_transactions(db_engine):
    def insert_batch(batch):
        with db_engine.begin() as conn:
            conn.execute(text("INSERT INTO materials(title) SELECT :prefix || i FROM generate_series(1, 20) i"), {'prefix': f'concurrent-{batch}-'})

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(insert_batch, range(5)))
    with db_engine.connect() as conn:
        assert_count(conn, 100)
