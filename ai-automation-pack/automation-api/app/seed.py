from app.config import get_settings
from app.database import Database
from app.demo import seed_demo_data


def main() -> None:
    database = Database(get_settings().database_url)
    database.create_schema()
    with database.session_factory() as db:
        seed_demo_data(db)
    database.dispose()
    print("Demo data is ready (idempotent).")


if __name__ == "__main__":
    main()
