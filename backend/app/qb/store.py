"""Save QuickBooks Rets into qb_records (the portal's copy of the company file)."""

from sqlalchemy.orm import Session

from ..models import QBRecord
from . import builder
from .registry import BY_RET, ENTITIES

DEL_TYPE_TO_KEYS: dict[str, list[str]] = {}
for _e in ENTITIES:
    if _e.del_type:
        DEL_TYPE_TO_KEYS.setdefault(_e.del_type, []).append(_e.key)


def upsert(db: Session, ret, company_id: int) -> tuple[QBRecord | None, bool]:
    """Store one Ret element. Returns (record, is_new); (None, False) for tags the portal does not track."""
    entity = BY_RET.get(ret.tag)
    if entity is None:
        return None, False
    data = builder.to_dict(ret)
    if not isinstance(data, dict):
        return None, False
    qb_id = data.get(entity.id_field)
    if not qb_id:
        return None, False
    rec = db.query(QBRecord).filter_by(company_id=company_id, entity=entity.key, qb_id=qb_id).first()
    is_new = rec is None
    if is_new:
        rec = QBRecord(company_id=company_id, entity=entity.key, qb_id=qb_id)
        db.add(rec)
    for k, v in builder.summary(entity, data).items():
        setattr(rec, k, v)
    rec.data, rec.deleted = data, False
    db.flush()
    return rec, is_new


def mark_deleted(db: Session, ret, company_id: int) -> bool:
    """ListDeletedRet / TxnDeletedRet -> flag the record as deleted."""
    del_type = ret.findtext("ListDelType") or ret.findtext("TxnDelType")
    qb_id = ret.findtext("ListID") or ret.findtext("TxnID")
    keys = DEL_TYPE_TO_KEYS.get(del_type or "", [])
    if not keys or not qb_id:
        return False
    n = db.query(QBRecord).filter(QBRecord.company_id == company_id, QBRecord.entity.in_(keys),
                                  QBRecord.qb_id == qb_id).update(
        {QBRecord.deleted: True}, synchronize_session=False)
    return n > 0


def process(db: Session, rets, company_id: int) -> tuple[int, int]:
    inserted = updated = 0
    for ret in rets:
        if not isinstance(ret.tag, str):
            continue
        if ret.tag in ("ListDeletedRet", "TxnDeletedRet"):
            updated += mark_deleted(db, ret, company_id)
            continue
        rec, is_new = upsert(db, ret, company_id)
        if rec is not None:
            inserted += is_new
            updated += not is_new
    return inserted, updated
