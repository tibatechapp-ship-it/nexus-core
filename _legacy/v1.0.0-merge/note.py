"""production_test — Note API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Note

router = APIRouter(prefix="/notes", tags=["Note"])


@router.get("/")
def list_notes(db: Session = Depends(get_db)):
    items = db.query(Note).all()
    return [item.to_dict() for item in items]


@router.get("/{item_id}")
def get_note(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Note).filter(Note.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Note not found")
    return item.to_dict()


@router.post("/")
def create_note(payload: dict, db: Session = Depends(get_db)):
    item = Note(**payload)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@router.delete("/{item_id}")
def delete_note(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Note).filter(Note.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}
