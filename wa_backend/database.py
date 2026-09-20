import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from config import Config
from sqlalchemy import event, text
from context import tenant_context

# +++ درع السحاب: معالجة بروتوكولات postgres و postgresql بمرونة تامة للـ SaaS +++
db_url = Config.SQLALCHEMY_DATABASE_URI
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if db_url.startswith("postgresql://") and "asyncpg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
DATABASE_URL = db_url

# إنشاء المحرك مع إعدادات الـ Pool التي وضعتها أنت سابقاً لمنع الشلل
engine = create_async_engine(
    DATABASE_URL,
    pool_size=Config.SQLALCHEMY_ENGINE_OPTIONS["pool_size"],
    max_overflow=Config.SQLALCHEMY_ENGINE_OPTIONS.get("max_overflow", 20),
    pool_recycle=Config.SQLALCHEMY_ENGINE_OPTIONS["pool_recycle"],
    pool_timeout=Config.SQLALCHEMY_ENGINE_OPTIONS["pool_timeout"],
    pool_use_lifo=Config.SQLALCHEMY_ENGINE_OPTIONS.get("pool_use_lifo", True),
    pool_pre_ping=True, # +++ الدرع المعماري (الحارس الآلي): فحص نبض الاتصال قبل سحبه لمنع كراش (Connection is closed) +++
    echo=False # غيرها لـ True فقط إذا أردت رؤية استعلامات SQL في التيرمنال
)

from sqlalchemy.exc import DisconnectionError

@event.listens_for(engine.sync_engine, "checkout")
def on_checkout(dbapi_connection, connection_record, connection_proxy):
    tenant_id = tenant_context.get()
    try:
        cursor = dbapi_connection.cursor()
        if tenant_id:
            # +++ الدرع الصارم (Allowlist Validation): +++
            # مشغل asyncpg ينهار عند استخدام Parameters (%s) داخل الـ Sync Events.
            # الحل الهندسي هو التحقق الصارم من أن الهوية أرقام أو UUID (أحرف وشرطات) فقط.
            # هذا يمنع SQL Injection بنسبة 100% ويسمح بدمج النص بأمان تام متخطياً ثغرة المشغل.
            t_str = str(tenant_id)
            if not all(c.isalnum() or c == '-' for c in t_str):
                raise ValueError("Invalid Tenant ID Format - Possible Injection")
            cursor.execute(f"SELECT set_config('app.current_tenant', '{t_str}', false)")
        else:
            cursor.execute("SELECT set_config('app.current_tenant', '', false)")
        cursor.close()
    except Exception as e:
        import logging
        logging.getLogger("wanasah_logger").error(f"DB Checkout RLS Security Error: {e}")
        raise DisconnectionError(f"RLS Setup Failed: {e}")

# (تم إعدام حدث on_checkin نهائياً: الاعتماد الكامل على إعادة البرمجة في on_checkout يمنع تسريب الـ asyncpg تماماً)

async def warm_async_engine_pool(
    target_engine: AsyncEngine,
    *,
    connections: int,
) -> None:
    """Open and validate exactly the steady-state pool connections.

    Every task keeps its connection until all requested connections have been
    checked out, which forces QueuePool to establish the full steady pool
    instead of repeatedly reusing one connection.
    """
    if connections <= 0:
        raise ValueError("connections must be positive")

    ready = 0
    ready_lock = asyncio.Lock()
    all_ready = asyncio.Event()

    async def warm_one() -> None:
        nonlocal ready
        async with target_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            async with ready_lock:
                ready += 1
                if ready == connections:
                    all_ready.set()
            await all_ready.wait()

    tasks = [
        asyncio.create_task(warm_one())
        for _ in range(connections)
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def warm_database_pool() -> None:
    await warm_async_engine_pool(
        engine,
        connections=int(
            Config.SQLALCHEMY_ENGINE_OPTIONS["pool_size"]
        ),
    )


# مصنع الجلسات (Session Factory)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# دالة حقن الاعتماديات (Dependency Injection) - قلب فاست إيه بي آي
async def get_db():
    # الـ async with تتكفل بالإغلاق والإعادة للـ Pool تلقائياً بأمان تام
    async with AsyncSessionLocal() as session:
        yield session