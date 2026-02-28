import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

# هذا هو كائن إعدادات Alembic، يوفر الوصول
# للقيم الموجودة في ملف .ini المستخدم.
config = context.config

# تفسير ملف الإعدادات لتسجيل بايثون.
# هذا السطر يقوم بإعداد مسجلات السجل بشكل أساسي.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


# --- دوال مساعدة للحصول على محرك وقاعدة بيانات Flask-SQLAlchemy ---
def get_engine():
    try:
        # يعمل مع Flask-SQLAlchemy<3 و Alchemical
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        # يعمل مع Flask-SQLAlchemy>=3
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# --- إعدادات الاتصال والبيانات الوصفية ---
# قم بتعيين رابط قاعدة البيانات من إعدادات Flask
config.set_main_option('sqlalchemy.url', get_engine_url())
target_db = current_app.extensions['migrate'].db

# إضافة كائن MetaData الخاص بنماذجك هنا
# لدعم 'autogenerate'
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# في حالتنا، Flask-SQLAlchemy يوفر هذا
def get_metadata():
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata

target_metadata = get_metadata()
# ---------------------------------------------


# --- إعدادات أخرى يمكن الحصول عليها من config ---
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
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
        target_metadata=target_metadata, # استخدام المتغير المعرف أعلاه
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # +++ تفعيل Batch Mode هنا أيضاً للاحتياط +++
        render_as_batch=True
        # +++++++++++++++++++++++++++++++++++++++++++++
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
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
            # Check if migration is auto-generated and upgrade_ops is empty
            if script.upgrade_ops is not None and script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')
            # Handle multi-db, optional
            # elif script.upgrade_ops_list is not None:
            #     empty = True
            #     for upgrade_ops in script.upgrade_ops_list:
            #         if not upgrade_ops.is_empty():
            #             empty = False
            #     if empty:
            #         directives[:] = []
            #         logger.info('No changes in schema detected.')


    # --- الحصول على conf_args وتعديله ---
    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    # +++ التأكد من تفعيل Batch Mode عن طريق إضافته للقاموس +++
    conf_args['render_as_batch'] = True
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++++
    # --------------------------------------

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata, # استخدام المتغير المعرف أعلاه
            **conf_args # تمرير القاموس المعدل الذي يحتوي render_as_batch=True
        )

        with context.begin_transaction():
            context.run_migrations()


# --- تحديد أي وضع سيتم تشغيله ---
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
# --- نهاية الملف ---