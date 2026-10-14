"""hello_api — Greeting API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Greeting

router = APIRouter(prefix="/greetings", tags=["Greeting"])


@router.get("/")
def list_greetings(db: Session = Depends(get_db)):
    items = db.query(Greeting).all()
    return [item.to_dict() for item in items]


@router.get("/{item_id}")
def get_greeting(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Greeting).filter(Greeting.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Greeting not found")
    return item.to_dict()


@router.post("/")
def create_greeting(payload: dict, db: Session = Depends(get_db)):
    item = Greeting(**payload)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@router.delete("/{item_id}")
def delete_greeting(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Greeting).filter(Greeting.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Greeting not found")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}
