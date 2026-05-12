from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Float, Integer, String, Text

class Base(DeclarativeBase):
    pass


class video(Base):
    __tablename__ = "video"
    id = Column(Integer, primary_key=True)
    filename = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    path = Column(String)
    cuts = Column(String)