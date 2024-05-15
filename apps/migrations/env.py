from __future__ import with_statement

import logging
from logging.config import fileConfig

import sqlalchemy
from alembic import context
from flask import current_app

from apps import enums
from apps.ext.offline_mix_planner.model import PlanningResultModel


__all__ = [enums, PlanningResultModel]


def my_compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # return False if the metadata_type is the same as the inspected_type
    # or None to allow the default implementation to compare these
    # types. a return value of True means the two types do not
    # match and should result in a type change operation.

    # 解决：alembic 无法检测到枚举类的变化.
    # https://github.com/sqlalchemy/alembic/issues/779#issuecomment-1248806093
    if isinstance(inspected_type, sqlalchemy.Enum) and isinstance(metadata_type, sqlalchemy.Enum):
        inspected_enum_values = set(inspected_type.enums)
        metadata_enum_values = set(metadata_type.enums)
        return inspected_enum_values != metadata_enum_values

    return None



# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.

config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
# fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
config.set_main_option(
    'sqlalchemy.url',
    str(current_app.extensions['migrate'].db.get_engine().url).replace(
        '%', '%%'
    )
)
target_metadata = current_app.extensions['migrate'].db.metadata


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

ignore_tables = {"wcs_alembic_version", "task_manager_model", "wcs_task_manager_cache", "wcs_workspace_manager_cache"}

# def include_name(name, type_, parent_names):
#     return type_ != "table" or name not in ignore_tables


def include_object(obj, name, type_, *args, **kwargs):
    return not (type_ == "table" and name in ignore_tables)


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        compare_type=my_compare_type,  # type: ignore
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    connectable = current_app.extensions['migrate'].db.get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
            include_object=include_object,
            compare_type=my_compare_type,  # type: ignore
            **current_app.extensions['migrate'].configure_args
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
