"""同票关系的登记、撤销、快照与分组预览。

并发约定：所有写路径先锁本批次的注册表行（没有则创建），再改关系记录，
锁序统一为 link_registries → ticket_links；每次生效变更在同一事务里递增
版本号，因此版本只增不减，运行发起时固定的快照永不被后续变更影响。
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.domain.groups import build_groups, display_order
from src.models.links import LinkRegistry, RunLinkSnapshot, TicketLink
from src.services.audit import record
from src.utils.time import now


def _registry(db, dataset_id, create):
    registry = db.get(LinkRegistry, dataset_id, with_for_update=True)
    if registry is None and create:
        registry = LinkRegistry(dataset_id=dataset_id, version=0)
        try:
            with db.begin_nested():
                db.add(registry)
                db.flush()
        except IntegrityError:
            # 并发创建同一批次的注册表行：回退到已提交的那一行并加锁。
            registry = db.get(LinkRegistry, dataset_id, with_for_update=True)
    return registry


def _active_pairs(db, dataset_id):
    query = (select(TicketLink.left_id, TicketLink.right_id)
             .where(TicketLink.dataset_id == dataset_id, TicketLink.active.is_(True))
             .order_by(TicketLink.id))
    return [[left, right] for left, right in db.execute(query)]


def current(db, dataset_id):
    """读取当前版本与生效关系。注册表行存在时持行锁读取，版本与关系必然一致。"""
    registry = _registry(db, dataset_id, create=False)
    return (registry.version if registry else 0), _active_pairs(db, dataset_id)


def register(db, dataset, left_id, right_id, actor):
    """登记同票关系；重复登记幂等返回，撤销过的关系重新激活。返回 (记录, 版本, 是否新生效)。"""
    if left_id == right_id:
        raise ValueError('同一件扫描件无需登记同票关系。')
    left_id, right_id = sorted((left_id, right_id))
    known = {row['document_id'] for row in dataset.rows}
    missing = [item for item in (left_id, right_id) if item not in known]
    if missing:
        raise ValueError(f'票据编号不在本批次中：{"、".join(missing)}。')
    registry = _registry(db, dataset.id, create=True)
    lookup = select(TicketLink).where(TicketLink.dataset_id == dataset.id,
                                      TicketLink.left_id == left_id,
                                      TicketLink.right_id == right_id)
    link = db.scalar(lookup.with_for_update())
    if link and link.active:
        return link, registry.version, False
    if link is None:
        link = TicketLink(dataset_id=dataset.id, left_id=left_id, right_id=right_id,
                          active=True, created_by=actor)
        try:
            with db.begin_nested():
                db.add(link)
                db.flush()
        except IntegrityError:
            # 并发登记同一对：以先提交的记录为准。
            link = db.scalar(lookup.with_for_update())
            if link is None:
                raise
            if link.active:
                return link, registry.version, False
    link.active = True
    link.revoked_by = None
    link.revoked_at = None
    registry.version += 1
    record(db, actor, 'link.registered', dataset.id, left=left_id, right=right_id, version=registry.version)
    return link, registry.version, True


def revoke(db, dataset, link_id, actor):
    """撤销关系：只标记不删除，版本递增；重复撤销幂等。返回 (记录, 版本)。"""
    registry = _registry(db, dataset.id, create=True)
    link = db.get(TicketLink, link_id, with_for_update=True)
    if link is None or link.dataset_id != dataset.id:
        raise LookupError(link_id)
    if link.active:
        link.active = False
        link.revoked_by = actor
        link.revoked_at = now()
        registry.version += 1
        record(db, actor, 'link.revoked', dataset.id,
               left=link.left_id, right=link.right_id, version=registry.version)
    return link, registry.version


def pin(db, run_id, dataset_id):
    """运行发起时在同一事务内固定版本与生效关系快照，供计算与重试使用。"""
    registry = _registry(db, dataset_id, create=True)
    db.add(RunLinkSnapshot(run_id=run_id, version=registry.version, links=_active_pairs(db, dataset_id)))
    return registry.version


def preview(db, dataset):
    """按当前生效关系分组，逐组给出成员、是否计入与原因。"""
    version, pairs = current(db, dataset.id)
    groups = [{
        'key': f'G{index}',
        'members': group['members'],
        'size': group['size'],
        'counted': group['consistent'],
        'reason': group['reason'],
    } for index, group in enumerate(display_order(build_groups(dataset.rows, pairs)), 1)]
    return version, groups
