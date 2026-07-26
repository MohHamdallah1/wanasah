from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import Config

# +++ درع السحاب: معالجة بروتوكولات postgres و postgresql بمرونة تامة للـ SaaS +++
db_url = Config.SQLALCHEMY_DATABASE_URI
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
DATABASE_URL = db_url.replace("postgresql://", "postgresql+asyncpg://")

# إنشاء المحرك مع إعدادات الـ Pool التي وضعتها أنت سابقاً لمنع الشلل
engine = create_async_engine(
    DATABASE_URL,
    pool_size=Config.SQLALCHEMY_ENGINE_OPTIONS["pool_size"],
    max_overflow=Config.SQLALCHEMY_ENGINE_OPTIONS.get("max_overflow", 20),
    pool_recycle=Config.SQLALCHEMY_ENGINE_OPTIONS["pool_recycle"],
    pool_timeout=Config.SQLALCHEMY_ENGINE_OPTIONS["pool_timeout"],
    echo=False # غيرها لـ True فقط إذا أردت رؤية استعلامات SQL في التيرمنال
)

# مصنع الجلسات (Session Factory)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# دالة حقن الاعتماديات (Dependency Injection) - قلب فاست إيه بي آي
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()