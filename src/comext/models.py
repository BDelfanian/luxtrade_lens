"""SQLAlchemy 2.x schema; classification codes intentionally have no lookup FKs."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata."""


class ImportedFile(Base):
    """Successfully committed source files and their provenance."""

    __tablename__ = "imported_files"

    source_path: Mapped[str] = mapped_column(String(512), primary_key=True)
    file_type: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    rows_loaded: Mapped[int] = mapped_column(BigInteger)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
    )


class TradeData(Base):
    """All eighteen original fields plus source identity and CSV record position."""

    __tablename__ = "trade_data"
    __table_args__ = (Index("ix_trade_reporter_period", "reporter", "period"),)

    source_path: Mapped[str] = mapped_column(
        String(512),
        ForeignKey("imported_files.source_path"),
        primary_key=True,
    )
    row_number: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    reporter: Mapped[str] = mapped_column(String(16))
    partner: Mapped[str] = mapped_column(String(16))
    trade_type: Mapped[str] = mapped_column(String(8))
    product_nc: Mapped[str] = mapped_column(String(32))
    product_sitc: Mapped[str | None] = mapped_column(String(32))
    product_cpa21: Mapped[str | None] = mapped_column(String(32))
    product_cpa22: Mapped[str | None] = mapped_column(String(32))
    product_bec: Mapped[str | None] = mapped_column(String(32))
    product_bec5: Mapped[str | None] = mapped_column(String(32))
    product_section: Mapped[str | None] = mapped_column(String(32))
    flow: Mapped[str] = mapped_column(String(8))
    stat_procedure: Mapped[str | None] = mapped_column(String(16))
    suppl_unit: Mapped[str | None] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(6))
    value_eur: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    value_nac: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    quantity_kg: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    quantity_suppl_unit: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))


class DimPartner(Base):
    """Official partner codes and their latest English names."""

    __tablename__ = "dim_partner"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name_en: Mapped[str] = mapped_column(Text)


class DimProductNC(Base):
    """Official CN descriptions qualified by classification year."""

    __tablename__ = "dim_product_nc"
    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    description_en: Mapped[str] = mapped_column(Text)
