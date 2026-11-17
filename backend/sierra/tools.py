import hashlib
import hmac
import re
import uuid
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .models import Coupon, Customer, Order, OrderEvent, Product, Ticket
from .planner import explicit_action
from .recommendation import ZH_FEATURES, extract_features
from .schemas import Evidence, Result

PACIFIC = ZoneInfo("America/Los_Angeles")
CAMPAIGN = "early-risers-v1"
LABELS = {
    "placed": ("已下单", "placed"), "in_transit": ("送货中", "in transit"),
    "delivered": ("已收到", "delivered"), "cancelled": ("已取消", "cancelled"),
    "return_requested": ("退货申请中", "return requested"),
    "unknown": ("状态待确认", "status needs review"), "error": ("订单异常", "order error"),
}


class Tools:
    def __init__(self, db, conversation, request_id, received_at, settings, search, policies):
        self.db, self.conv, self.request_id = db, conversation, request_id
        self.received_at, self.settings = received_at, settings
        self.search, self.policies = search, policies
        self.state = dict(conversation.state)
        self.zh = self.state.get("language") == "zh"

    def say(self, zh, en):
        return zh if self.zh else en

    def policy(self, name):
        return Evidence(id=f"policy:{name}:{self.policies['version']}", kind="policy",
                        label=f"Sierra · {name} · {self.policies['version']}",
                        facts={"version": self.policies["version"], "rule": self.policies[name]})

    def extract(self, message):
        email = re.search(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", message, re.I)
        number = re.search(r"(?<![A-Z0-9])#?((?:W|DEMO)\d{3})(?![A-Z0-9])", message, re.I)
        if email:
            self.state["email"] = email.group().lower()
        if number:
            next_number = "#" + number.group(1).upper()
            if next_number != self.state.get("current_order"):
                self.state.pop("pending_confirmation", None)
                self.state.pop("current_order", None)
            self.state["order_number"] = next_number

    def find_order(self, workflow, message):
        self.extract(message)
        number = self.state.get("order_number") or self.state.get("current_order")
        customer = self.db.get(Customer, self.conv.customer_id) if self.conv.customer_id else None
        email = self.state.get("email") or (customer.email if customer else None)
        if not email or not number:
            self.state["pending"] = workflow
            needed = self.say("邮箱和订单号" if not email and not number else "邮箱" if not email else "订单号",
                              "your email and order number" if not email and not number else "your email" if not email else "your order number")
            return None, Result(workflow=workflow, status="needs_input", text=self.say(
                f"请提供{needed}，我来帮你找到这次旅程的订单。🏔️",
                f"Please share {needed} so I can find your order. 🏔️"), evidence=[self.policy("order_lookup")])
        order = self.db.scalar(select(Order).join(Customer).where(Order.number == number, Customer.email == email))
        if order is None or (customer and order.customer_id != customer.id):
            # Clear the target and confirmation; never fall back to a previously verified order.
            self.state.pop("current_order", None)
            self.state.pop("pending_confirmation", None)
            self.state["pending"] = workflow
            return None, Result(workflow=workflow, status="not_found", text=self.say(
                "没有找到匹配的订单，请核对邮箱和订单号。", "No matching order was found. Please check the email and order number."),
                evidence=[self.policy("order_lookup")])
        self.state["current_order"] = order.number
        self.state["order_number"] = order.number
        grants = self.state.get("verified_orders", [])
        self.state["verified_orders"] = list(dict.fromkeys(grants + [order.number]))[-10:]
        self.state.pop("pending", None)
        return order, None

    def order_evidence(self, order):
        return Evidence(id=f"order:{order.number}:v{order.version}", kind="order", label=f"Order {order.number}", facts={
            "order_number": order.number, "state": order.state, "source_status": order.raw_status,
            "tracking_number": order.tracking, "product_skus": order.product_skus,
            "version": order.version, "demo_fixture": order.is_demo,
        })

    def order_view(self, order):
        evidence = self.order_evidence(order)
        tracking_url = "https://tools.usps.com/go/TrackConfirmAction?tLabels=" + quote(order.tracking, safe="") if order.tracking else None
        label = LABELS[order.state][0 if self.zh else 1]
        return {**evidence.facts, "status_label": label, "tracking_url": tracking_url}

    def lookup(self, message):
        order, error = self.find_order("lookup", message)
        if error:
            return error
        if order.state in {"unknown", "error"}:
            return self.handoff("order_state_review", f"Review {order.number}: {order.raw_status}", [self.order_evidence(order)])
        data = self.order_view(order)
        text = self.say(f"订单 {order.number}：{data['status_label']}。", f"Order {order.number} is {data['status_label']}.")
        if not order.tracking:
            text += self.say("目前没有可用的物流单号。", " A tracking number is not available yet.")
        else:
            text += self.say("可通过下方 USPS 链接查看物流。🏔️", " Follow its journey using the USPS link below. 🏔️")
        actions = []
        if order.state == "placed":
            actions = [{"label": self.say("取消此订单", "Cancel this order"), "message": f"Cancel order {order.number}"}]
        elif order.state == "delivered":
            actions = [{"label": self.say("申请退货", "Request a return"), "message": f"Request a return for order {order.number}"}]
        return Result(workflow="lookup", status="ok", text=text, evidence=[self.order_evidence(order)], data=data, actions=actions)

    def order_action(self, action, message):
        order, error = self.find_order(action, message)
        if error:
            return error
        evidence = [self.order_evidence(order), self.policy("order_actions")]
        if self.conv.customer_id != order.customer_id:
            self.state["pending"] = action
            return Result(workflow=action, status="authentication_required", text=self.say(
                "订单信息已匹配。取消或申请退货前，请使用该订单所属的测试账户登录；邮箱和订单号不等同于身份认证。",
                "The order matches. Please sign in as its owner before cancelling or requesting a return. Email and order number alone do not authenticate an account."), evidence=evidence)
        expected, target = ("placed", "cancelled") if action == "cancel" else ("delivered", "return_requested")
        if order.state == target:
            return Result(workflow=action, status="already_done", text=self.say(
                f"订单 {order.number} 已是「{LABELS[target][0]}」，无需重复提交。",
                f"Order {order.number} is already {LABELS[target][1]}; no duplicate action was created."), evidence=evidence, data=self.order_view(order))
        if order.state in {"error", "unknown"}:
            return self.handoff("order_state_review", f"Review {order.number}: {order.raw_status}", evidence)
        if order.state != expected:
            return Result(workflow=action, status="not_allowed", text=self.say(
                f"订单 {order.number} 当前为「{LABELS[order.state][0]}」，不符合本次操作条件。仅已下单可取消、已收到可申请退货。",
                f"Order {order.number} is {LABELS[order.state][1]}. Only placed orders may be cancelled; only delivered orders may have a return requested."), evidence=evidence, data=self.order_view(order))
        if not explicit_action(message, action, self.state):
            self.state["pending"] = action
            self.state["pending_confirmation"] = action
            return Result(workflow=action, status="needs_confirmation", text=self.say(
                f"订单 {order.number} 符合{'取消' if action == 'cancel' else '申请退货'}条件。要提交这项操作吗？",
                f"Order {order.number} is eligible. Would you like me to {'cancel it' if action == 'cancel' else 'submit a return request'}?"), evidence=evidence,
                actions=[{"label": self.say("确认提交", "Confirm request"), "message": f"{'Cancel' if action == 'cancel' else 'Request a return for'} order {order.number}"}])
        previous, version = order.state, order.version
        changed = self.db.execute(update(Order).where(Order.number == order.number, Order.customer_id == self.conv.customer_id,
                                                      Order.state == expected, Order.version == version)
                                  .values(state=target, version=version + 1).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            self.db.refresh(order)
            return Result(workflow=action, status="conflict", text=self.say(
                "订单状态刚刚变化，请重新查询后再操作。", "The order changed while processing your request. Please check its latest state."), evidence=[self.order_evidence(order)])
        event = OrderEvent(conversation_id=self.conv.id, request_id=self.request_id, order_number=order.number,
                           action=action, before=previous, after=target)
        self.db.add(event)
        self.db.flush()
        self.db.refresh(order)
        self.state.pop("pending", None)
        self.state.pop("pending_confirmation", None)
        text = self.say(f"订单 {order.number} 已取消。", f"Order {order.number} has been cancelled.") if action == "cancel" else self.say(
            f"订单 {order.number} 的退货申请已保存。尚未执行退款，也未生成退货运单；后续处理需要人工审核。",
            f"Your return request for {order.number} is saved. No refund or return label has been issued; further processing needs human review.")
        return Result(workflow=action, status="success", text=text, evidence=[self.order_evidence(order), self.policy("order_actions"),
                      Evidence(id=f"event:{event.id}", kind="event", label="Saved order action", facts={
                          "order_number": order.number, "action": action, "before": previous, "after": target})], data=self.order_view(order))

    def recommend(self, query):
        previous = self.state.get("preferences", "")
        if re.search(r"还有|更|比较|区别|another|lighter|compare|difference|more", query, re.I) and previous:
            query = (previous + " " + query)[-600:]
        self.state["preferences"] = query[:600]
        rows = self.search.search(query)
        if not rows:
            return Result(workflow="recommend", status="no_match", text=self.say(
                "目录中没有找到有足够依据的匹配商品。可以告诉我商品类型或换一个需求吗？",
                "I couldn't find a supported match in this catalogue. Could you share the product type or another preference?"),
                evidence=[Evidence(id="policy:catalogue-scope", kind="policy", label="Catalogue scope", facts={"rule": "Only supplied catalogue products and explicit attributes may be recommended."})])
        self.state["last_products"] = [p["sku"] for p in rows]
        evidence, products = [], []
        for row in rows:
            # Refresh inventory and source text from the transaction's current catalogue.
            product = self.db.get(Product, row["sku"])
            if not product or product.inventory <= 0:
                continue
            features = [ZH_FEATURES[f] if self.zh else f for f in extract_features(product.description)]
            evidence.append(Evidence(id=f"product:{product.sku}", kind="product", label=product.name,
                                     facts={"sku": product.sku, "name": product.name, "description": product.description,
                                            "inventory": product.inventory, "tags": product.tags}))
            products.append({"sku": product.sku, "name": product.name, "inventory": product.inventory,
                             "description": product.description, "tags": product.tags, "features": features,
                             "score": row["score"]})
        if not products:
            return Result(workflow="recommend", status="no_match", text=self.say("匹配商品当前没有库存。", "The matching products are currently unavailable."))
        text = self.say("这些商品与需求相关，特点均来自目录。🏔️", "These catalogue matches may fit your next adventure. 🏔️")
        if len(products) == 1:
            text += self.say("目录中只找到这一款匹配商品，无法提供多款对比。", " Only one supported match is available, so a multi-product comparison isn't possible.")
        if re.search(r"价格|多少钱|便宜|重量|多重|升|尺码|price|cheaper|weight|litres|liters|size", query, re.I):
            text += self.say("目录未提供价格、重量、容量数值或尺码，无法据此筛选。", " The catalogue does not specify price, weight, volume or sizes, so I cannot filter on those values.")
        return Result(workflow="recommend", status="ok", text=text, evidence=evidence, data={"products": products, "query": query})

    def coupon(self, message):
        policy = self.policy("early_risers")
        if not self.conv.customer_id:
            self.state["pending"] = "coupon"
            return Result(workflow="coupon", status="authentication_required", text=self.say(
                "请先登录测试账户，我才能确认领取身份并检查是否领过优惠码。", "Please sign in to a demo account so I can check its existing promotion claim."), evidence=[policy])
        customer = self.db.scalar(select(Customer).where(Customer.id == self.conv.customer_id).with_for_update())
        existing = self.db.scalar(select(Coupon).where(Coupon.customer_id == customer.id, Coupon.campaign == CAMPAIGN))
        if existing:
            return self.coupon_result(existing, "existing", [policy])
        if (re.search(r"不要|不想|不用|don't|do not|never", message, re.I)
                or not re.search(r"领取|领个|给我|申请|我要|claim|give me|send me|request|I'd like|I want|can I get", message, re.I)):
            return Result(workflow="coupon", status="information", text=self.say(
                "早鸟活动提供九折优惠，每位客户可领一次。请在美国太平洋时间 08:00–10:00 明确提出领取。",
                "Early Risers offers 10% off, once per customer. Explicitly request a code between 08:00 and 10:00 Pacific Time."), evidence=[policy],
                actions=[{"label": self.say("领取早鸟优惠", "Claim Early Risers"), "message": "I want to claim the Early Risers Promotion"}])
        local = self.received_at.astimezone(PACIFIC)
        clock = Evidence(id="clock:receipt", kind="clock", label="Server message receipt · Pacific", facts={
            "received_at": self.received_at.isoformat(), "pacific_time": local.isoformat(), "timezone": "America/Los_Angeles"})
        if not 8 <= local.hour < 10:
            return Result(workflow="coupon", status="outside_window", text=self.say(
                f"这条消息收到时，美国太平洋时间为 {local:%H:%M}，不在 08:00–10:00 的领取时段内。",
                f"Your message arrived at {local:%H:%M} Pacific Time, outside the 08:00–10:00 claim window."), evidence=[policy, clock])
        digest = hmac.new(self.settings.coupon_secret.encode(), f"{CAMPAIGN}:{customer.id}".encode(), hashlib.sha256).hexdigest().upper()
        # Savepoints recover from a duplicate customer claim or a truncated-code collision.
        for length in (16, 24, 32):
            coupon = Coupon(customer_id=customer.id, campaign=CAMPAIGN, code="RISE-" + digest[:length], created_at=self.received_at)
            try:
                with self.db.begin_nested():
                    self.db.add(coupon)
                    self.db.flush()
                self.state.pop("pending", None)
                return self.coupon_result(coupon, "issued", [policy, clock])
            except IntegrityError:
                existing = self.db.scalar(select(Coupon).where(Coupon.customer_id == customer.id, Coupon.campaign == CAMPAIGN))
                if existing:
                    return self.coupon_result(existing, "existing", [policy, clock])
        raise RuntimeError("Coupon uniqueness could not be established")

    def coupon_result(self, coupon, status, evidence):
        return Result(workflow="coupon", status=status, text=self.say(
            f"{'已找到你领取的' if status == 'existing' else '已为你生成'}九折优惠码：{coupon.code}。🏔️ 此演示尚未连接结账核销。",
            f"{'Your existing' if status == 'existing' else 'Your new'} 10% discount code is {coupon.code}. 🏔️ Checkout redemption is not connected in this demo."),
            evidence=evidence + [Evidence(id=f"coupon:{coupon.id}", kind="coupon", label="Saved Early Risers claim", facts={
                "code": coupon.code, "campaign": coupon.campaign, "discount_percent": coupon.discount_percent})],
            data={"code": coupon.code, "discount_percent": coupon.discount_percent, "campaign": coupon.campaign})

    def handoff(self, reason, summary, evidence=None):
        ticket = self.db.scalar(select(Ticket).where(Ticket.conversation_id == self.conv.id, Ticket.request_id == self.request_id))
        if ticket is None:
            ticket = Ticket(conversation_id=self.conv.id, request_id=self.request_id, reference="SIERRA-" + uuid.uuid4().hex[:12].upper(),
                            reason=reason, summary=summary[:1000], evidence=[e.model_dump() for e in (evidence or [])])
            self.db.add(ticket)
            self.db.flush()
        return Result(workflow="handoff", status="ticket_created", text=self.say(
            f"已保存人工处理工单 {ticket.reference}。当前演示没有实时客服连接，暂不能承诺回复时间。",
            f"Support ticket {ticket.reference} is saved. This demo has no live-agent connection or guaranteed response time."),
            evidence=(evidence or []) + [self.policy("handoff"), Evidence(id=f"ticket:{ticket.id}", kind="ticket", label="Saved support ticket",
                                                                        facts={"reference": ticket.reference, "status": ticket.status, "reason": ticket.reason})],
            data={"reference": ticket.reference, "status": ticket.status, "reason": ticket.reason})

    def policy_answer(self, message):
        return self.handoff("return_policy_undefined", self.say("客户询问初版未定义的退货退款政策。", "Customer requested return/refund policy details that are not defined in the MVP."), [self.policy("returns")])
