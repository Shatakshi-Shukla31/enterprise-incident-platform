"""Rebuild the demo database from scratch: python -m scripts.reset_demo --yes

Drops every table, recreates the schema and loads fresh synthetic data, so the hosted demo
never goes stale and nothing a visitor typed survives. It deletes everything, so point it
only at a database that holds the demo and nothing else.
"""

import argparse
import logging

from sqlalchemy import text

from app.db.migrations import upgrade_to_head
from app.db.session import get_engine
from scripts import seed_demo

logger = logging.getLogger("reset")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm that every table may be deleted")
    parser.add_argument("--incidents", type=int, default=800)
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("This deletes every table. Run it again with --yes to confirm.")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # The audit trigger forbids deleting audit rows one by one; dropping the schema is the
    # only way to clear them, and the migration recreates the trigger with everything else.
    with get_engine().begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    get_engine().dispose()
    logger.info("Schema dropped")

    upgrade_to_head()
    seed_demo.load(args.incidents)
    logger.info("Demo rebuilt")


if __name__ == "__main__":
    main()
