from alembic import context

from modellab_api.db import Base, make_engine

url = context.config.get_main_option("sqlalchemy.url")
engine = make_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
