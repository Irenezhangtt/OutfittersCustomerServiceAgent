import json

from sqlalchemy import delete, select

from .models import Message


def context_snapshot(db, conversation):
    rows = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id)
                           .order_by(Message.id.desc()).limit(12)))
    return {"summary": conversation.summary, "state": conversation.state,
            "recent": [{"role": m.role, "content": m.content} for m in reversed(rows)]}


def compact(db, conversation, budget):
    """Conservative character budget bounds tokens without an extra model call.

    The summary is rebuilt only from allowlisted structured state, never extracted
    instructions. Old messages are deleted; business audit events remain separate.
    """
    db.flush()
    rows = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id)
                           .order_by(Message.id)))
    state = conversation.state
    summary = {k: state[k] for k in ("current_order", "pending", "preferences", "last_products", "language")
               if k in state}
    # Leave at least half the budget available to tool evidence and future output.
    history_budget = max(500, budget // 2 - len(json.dumps(summary, ensure_ascii=False)))
    total = sum(len(m.content) for m in rows)
    remove = []
    while rows and (total > history_budget or len(rows) > 12):
        row = rows.pop(0)
        total -= len(row.content)
        remove.append(row.id)
    if remove:
        db.execute(delete(Message).where(Message.id.in_(remove)))
        conversation.summary = {**summary, "compacted_messages": conversation.summary.get("compacted_messages", 0) + len(remove)}
    return {"recent_messages": len(rows), "compacted_messages": conversation.summary.get("compacted_messages", 0),
            "history_chars": total, "budget_chars": budget}
