from enishi_core.models import Base
from enishi_core.services import second_brain
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_internal_second_brain_works_without_external_source() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = second_brain.ensure_local_user(session)
        second_brain.remember(
            session,
            user_id=user.id,
            title="UI方針",
            text="ネイティブなmacOS UIを優先する",
            memory_type="decision",
        )
        results = second_brain.search(session, user_id=user.id, query="macOS")
        assert [item.title for item in results] == ["UI方針"]
