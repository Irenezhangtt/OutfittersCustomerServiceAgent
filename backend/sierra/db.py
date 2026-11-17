import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from .models import Base, Customer, Order, Product


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def make_database(url):
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 10}
    else:
        options["connect_args"] = {"connect_timeout": 3, "options": "-c statement_timeout=3000 -c lock_timeout=2000"}
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def setup(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
    return engine, sessionmaker(engine, expire_on_commit=False)


def seed_database(engine, sessions, settings):
    Base.metadata.create_all(engine)
    with sessions.begin() as db:
        # A first-start seed; persistent user actions are never reset on restart.
        if db.scalar(select(Customer.id).limit(1)) is not None:
            return
        customers = {}
        rows = json.loads((settings.order_data_path or settings.data_dir / "CustomerOrders.json").read_text())
        if settings.demo_mode:
            rows += json.loads((settings.data_dir / "DemoOrders.json").read_text())
        mapping = {"delivered": "delivered", "in-transit": "in_transit", "placed": "placed", "error": "error"}
        for row in rows:
            email = row["Email"].strip().lower()
            if email not in customers:
                customer = Customer(email=email, name=row["CustomerName"])
                db.add(customer)
                db.flush()
                customers[email] = customer.id
            db.add(Order(number=row["OrderNumber"].upper(), customer_id=customers[email],
                         raw_status=row["Status"], state=mapping.get(row["Status"], "unknown"),
                         product_skus=row["ProductsOrdered"], tracking=row["TrackingNumber"],
                         is_demo=row.get("DemoFixture", False)))
        for row in json.loads((settings.data_dir / "ProductCatalog.json").read_text()):
            db.add(Product(sku=row["SKU"], name=row["ProductName"], description=row["Description"],
                           tags=row["Tags"], inventory=row["Inventory"]))
