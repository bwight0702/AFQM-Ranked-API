from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import os

# 1. HANDLE CLOUD DATABASE ENV STRINGS
# Railway provides a 'postgresql://' URL, but async python libraries require 'postgresql+asyncpg://'
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./matchmaking.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# 2. SQLALCHEMY ENGINE SETUP
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# 3. DEFINE DATABASE MODEL
class Base(DeclarativeBase):
    pass

class PlayerTable(Base):
    __tablename__ = "players"
    
    player_id: Mapped[str] = mapped_column(sqlalchemy.String, primary_key=True)
    mu: Mapped[float] = mapped_column(sqlalchemy.Float, default=25.0)
    sigma: Mapped[float] = mapped_column(sqlalchemy.Float, default=8.3333)

# 4. FASTAPI APP INIT
app = FastAPI(title="Matchmaking API")

# Automated table generation on application boot
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

class UpdateRatingPayload(BaseModel):
    mu: float
    sigma: float

# ENDPOINT: Get player data
@app.get("/players/{player_id}")
async def get_player(player_id: str):
    async with async_session() as session:
        result = await session.execute(
            sqlalchemy.select(PlayerTable).where(PlayerTable.player_id == player_id)
        )
        player = result.scalar_one_or_none()
        
        if not player:
            # Create user inline if they don't exist yet
            player = PlayerTable(player_id=player_id, mu=25.0, sigma=8.3333)
            session.add(player)
            await session.commit()
            
        return {"player_id": player.player_id, "mu": player.mu, "sigma": player.sigma}

# ENDPOINT: Update player rating data from local bot calculations
@app.put("/players/{player_id}")
async def update_player(player_id: str, payload: UpdateRatingPayload):
    async with async_session() as session:
        result = await session.execute(
            sqlalchemy.select(PlayerTable).where(PlayerTable.player_id == player_id)
        )
        player = result.scalar_one_or_none()
        
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
            
        player.mu = payload.mu
        player.sigma = payload.sigma
        await session.commit()
        return {"status": "success", "player_id": player_id, "mu": player.mu, "sigma": player.sigma}

# ENDPOINT: Get global leaderboard
@app.get("/leaderboard")
async def get_leaderboard():
    async with async_session() as session:
        result = await session.execute(
            sqlalchemy.select(PlayerTable).order_by(PlayerTable.mu.desc()).limit(10)
        )
        players_rows = result.scalars().all()
        return [{"player_id": p.player_id, "mu": p.mu, "sigma": p.sigma} for p in players_rows]
