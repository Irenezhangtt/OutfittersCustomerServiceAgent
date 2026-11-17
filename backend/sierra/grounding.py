from sqlalchemy import select

from .models import Coupon, Order, OrderEvent, Product, Ticket
from .recommendation import ZH_FEATURES, extract_features


class GroundingError(RuntimeError):
    pass


def verify_results(db, conv, state, results, policies):
    """Validate all business evidence and persisted operations before commit/output.

    User-facing business prose is rendered by trusted templates, never by an
    unconstrained LLM. Product features are extracted from explicit source text.
    """
    for result in results:
        if result.status in {"ok", "success", "issued", "existing", "ticket_created", "already_done"} and not result.evidence:
            raise GroundingError("Successful business response has no evidence")
        product_sources = set()
        for item in result.evidence:
            facts = item.facts
            if item.kind == "order":
                order = db.get(Order, facts["order_number"])
                permitted = order and ((conv.customer_id == order.customer_id) if conv.customer_id else order.number in state.get("verified_orders", []))
                if not permitted or any(facts.get(k) != v for k, v in {
                    "state": order.state, "source_status": order.raw_status, "version": order.version,
                    "tracking_number": order.tracking, "product_skus": order.product_skus,
                }.items()):
                    raise GroundingError("Order evidence or ownership mismatch")
            elif item.kind == "product":
                product = db.get(Product, facts["sku"])
                if not product or any(facts.get(k) != getattr(product, k) for k in ("name", "description", "inventory", "tags")):
                    raise GroundingError("Catalogue evidence mismatch")
                product_sources.add(product.sku)
            elif item.kind == "coupon":
                coupon = db.scalar(select(Coupon).where(Coupon.code == facts["code"], Coupon.customer_id == conv.customer_id))
                if not coupon or coupon.campaign != facts["campaign"] or coupon.discount_percent != facts["discount_percent"]:
                    raise GroundingError("Coupon persistence or ownership mismatch")
            elif item.kind == "event":
                event = db.get(OrderEvent, item.id.removeprefix("event:"))
                if not event or event.conversation_id != conv.id or event.after != facts["after"] or event.order_number != facts["order_number"]:
                    raise GroundingError("Operation was not persisted")
            elif item.kind == "ticket":
                ticket = db.get(Ticket, item.id.removeprefix("ticket:"))
                if not ticket or ticket.conversation_id != conv.id or ticket.reference != facts["reference"]:
                    raise GroundingError("Ticket was not persisted")
            elif item.kind == "policy" and facts.get("version"):
                name = item.id.split(":")[1]
                if facts["version"] != policies["version"] or facts["rule"] != policies.get(name):
                    raise GroundingError("Policy evidence mismatch")
        for product in result.data.get("products", []):
            if product["sku"] not in product_sources:
                raise GroundingError("Recommendation lacks source")
            source = db.get(Product, product["sku"])
            if any(product.get(k) != getattr(source, k) for k in ("name", "description", "inventory", "tags")):
                raise GroundingError("Product card disagrees with evidence")
            allowed = extract_features(source.description)
            allowed += [ZH_FEATURES[f] for f in allowed]
            if any(feature not in allowed for feature in product.get("features", [])):
                raise GroundingError("Product feature is not supported")
        if result.workflow in {"cancel", "return"} and result.status == "success" and not any(e.kind == "event" for e in result.evidence):
            raise GroundingError("Action success lacks saved event")
