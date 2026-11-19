"""Migrate only the named isolated acceptance databases, never business data."""
import argparse
import os
from alembic import command
from alembic.config import Config
from release_support import engine, environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',choices=['wetchat_acceptance','wetchat_acceptance_perf'])
    args=parser.parse_args()
    os.environ['DATABASE_URL']=engine(args.database).url.render_as_string(hide_password=False)
    os.environ['APP_SECRET_KEY']=environment()['APP_SECRET_KEY']
    command.upgrade(Config('alembic.ini'),'head')
    print('isolated migration completed',flush=True)


if __name__=='__main__':
    main()
