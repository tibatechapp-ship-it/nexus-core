"""blog_api — Comment API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Comment

router = APIRouter(prefix="/comments", tags=["Comment"])


@router.get("/")
def list_comments(db: Session = Depends(get_db)):
    items = db.query(Comment).all()
    return [item.to_dict() for item in items]


@router.get("/{item_id}")
def get_comment(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Comment).filter(Comment.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Comment not found")
    return item.to_dict()


@router.post("/")
def create_comment(payload: dict, db: Session = Depends(get_db)):
    item = Comment(**payload)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@router.delete("/{item_id}")
def delete_comment(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Comment).filter(Comment.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Comment not found")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}
