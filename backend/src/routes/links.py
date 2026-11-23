from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.models.identity import User
from src.models.links import TicketLink
from src.models.source import Dataset
from src.schemas.requests import LinkRequest
from src.services import links as registry
from src.utils import views

router = APIRouter(prefix='/datasets/{dataset_id}')


def require_dataset(db, dataset_id):
    item = db.get(Dataset, dataset_id)
    if not item:
        raise HTTPException(404, '找不到该数据批次')
    return item


@router.get('/links')
def index(dataset_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    dataset = require_dataset(db, dataset_id)
    version, _pairs = registry.current(db, dataset.id)
    records = db.scalars(select(TicketLink).where(TicketLink.dataset_id == dataset.id)
                         .order_by(TicketLink.id.desc()).limit(200))
    return {'version': version, 'links': [views.link(item) for item in records]}


@router.post('/links', status_code=201)
def register(dataset_id: int, body: LinkRequest, db: Session = Depends(connection),
             actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    dataset = require_dataset(db, dataset_id)
    link, version, created = registry.register(db, dataset, body.left_id, body.right_id, actor.username)
    db.commit()
    return {**views.link(link), 'version': version, 'created': created}


@router.post('/links/{link_id}/revoke')
def revoke(dataset_id: int, link_id: int, db: Session = Depends(connection),
           actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    dataset = require_dataset(db, dataset_id)
    try:
        link, version = registry.revoke(db, dataset, link_id, actor.username)
    except LookupError:
        raise HTTPException(404, '找不到该同票关系') from None
    db.commit()
    return {**views.link(link), 'version': version}


@router.get('/groups')
def groups(dataset_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    dataset = require_dataset(db, dataset_id)
    version, items = registry.preview(db, dataset)
    return {'version': version, 'groups': items}
