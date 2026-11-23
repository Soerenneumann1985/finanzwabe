"""Database tables (SQLAlchemy 2.x) and the database session.

Money is always stored as integer cents. Every row belongs to exactly one
user, and every query in the app filters by user_id, so users never see
each other's data.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint,
    create_engine, event, inspect, text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, scoped_session, sessionmaker,
)

ACCOUNT_TYPES = {
    "giro": "Girokonto",
    "savings": "Sparkonto",
    "depot": "Depot",
    "cash": "Bargeld",
    "credit_card": "Kreditkarte",
}

CATEGORY_KINDS = {
    "expense": "Ausgabe",
    "income": "Einnahme",
    "transfer": "Umbuchung",
}

# One session per request/thread; the app removes it after each request.
db = scoped_session(sessionmaker(expire_on_commit=False))


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    accepted_terms_at: Mapped[dt.datetime | None] = mapped_column(DateTime)  # AGB accepted at registration


class Account(Base):
    """Girokonto, Sparkonto, Depot, Bargeld or Kreditkarte.

    The current balance is calculated, not stored:
    base_balance_cents + bookings on this account
    - bookings that name this account as counter account.
    """

    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(20))
    base_balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    credit_limit_cents: Mapped[int | None] = mapped_column(Integer)

    @property
    def type_label(self) -> str:
        return ACCOUNT_TYPES.get(self.type, self.type)


class Category(Base):
    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(10))
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_cents: Mapped[int | None] = mapped_column(Integer)  # monthly limit, expenses only

    @property
    def kind_label(self) -> str:
        return CATEGORY_KINDS.get(self.kind, self.kind)


class Transaction(Base):
    """One booking. Positive amount = income, negative = expense.

    counter_account_id is only used for transfers between two own accounts
    (e.g. Girokonto -> Sparkonto): the money leaving account_id arrives there.
    """

    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200), default="")
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), index=True)
    counter_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL"), index=True)
    recurring_id: Mapped[int | None] = mapped_column(ForeignKey("recurring.id", ondelete="SET NULL"))
    # Reference number from the bank export (OLB: "Kundenreferenz"). Only set by the bank import
    # and used to recognise the same booking on the next import. Optional, so
    # add_missing_columns() can add it to an existing database.
    customer_reference: Mapped[str | None] = mapped_column(String(64))

    category: Mapped[Category] = relationship()
    account: Mapped[Account] = relationship(foreign_keys=[account_id])
    counter_account: Mapped[Account | None] = relationship(foreign_keys=[counter_account_id])


class Recurring(Base):
    """Standing order (Dauerauftrag): booked automatically every month."""

    __tablename__ = "recurring"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    amount_cents: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    counter_account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id", ondelete="SET NULL"))
    day_of_month: Mapped[int] = mapped_column(Integer)
    next_date: Mapped[dt.date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[Category] = relationship()
    account: Mapped[Account] = relationship(foreign_keys=[account_id])
    counter_account: Mapped[Account | None] = relationship(foreign_keys=[counter_account_id])


class ImportRule(Base):
    """What the user made of a bank booking text in the bank import.

    key is the shortened bank text (e.g. "paypal lidl s"). The next import
    suggests the same description and category for that key.
    """

    __tablename__ = "import_rule"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(200), default="")
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"))


class Loan(Base):
    __tablename__ = "loan"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    start_amount_cents: Mapped[int] = mapped_column(Integer)
    monthly_rate_cents: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[dt.date] = mapped_column(Date)  # date of the first rate
    interest_rate_bp: Mapped[int] = mapped_column(Integer, default=0)  # 349 = 3.49 % p.a.


class NetWorthSnapshot(Base):
    """Net worth at the end of a month, recorded automatically for the history chart."""

    __tablename__ = "net_worth_snapshot"
    __table_args__ = (UniqueConstraint("user_id", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    month: Mapped[dt.date] = mapped_column(Date)  # always the first day of the month
    assets_cents: Mapped[int] = mapped_column(Integer)
    debts_cents: Mapped[int] = mapped_column(Integer)


def init_db(url: str) -> Engine:
    """Connect to the database, create missing tables and add missing columns."""
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    db.remove()
    db.configure(bind=engine)
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    return engine


def add_missing_columns(engine: Engine) -> list[str]:
    """Small automatic migration: new optional columns are added to existing tables.

    create_all() only creates missing tables. A database that already holds real
    data would otherwise lack columns added to the models later. Only additive,
    optional (nullable) columns are handled; anything else needs a real migration.
    """
    inspector = inspect(engine)
    added = []
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    raise RuntimeError(f"Spalte {table.name}.{column.name} braucht eine echte Migration.")
                column_type = column.type.compile(engine.dialect)
                connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))
                added.append(f"{table.name}.{column.name}")
    return added


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    # SQLite ignores foreign keys (and ON DELETE CASCADE) unless switched on.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
