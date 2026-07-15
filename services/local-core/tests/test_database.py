from pathlib import Path

from sqlalchemy import text


def test_file_database_initializes_through_alembic(tmp_path: Path) -> None:
    from twinlink_core.database import init_database

    database_path = tmp_path / "twinlink.db"
    engine = init_database(f"sqlite:///{database_path}")

    with engine.connect() as connection:
        version = connection.execute(text("select version_num from alembic_version")).scalar_one()
        tables = {
            row[0]
            for row in connection.execute(
                text("select name from sqlite_master where type = 'table'")
            )
        }

    assert version == "202607130003"
    assert {"personal_agents", "device_nodes"} <= tables
