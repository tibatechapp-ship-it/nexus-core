"""blog_api — Post API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Post

router = APIRouter(prefix="/posts", tags=["Post"])


@router.get("/")
def list_posts(db: Session = Depends(get_db)):
    items = db.query(Post).all()
    return [item.to_dict() for item in items]


@router.get("/{item_id}")
def get_post(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Post).filter(Post.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Post not found")
    return item.to_dict()


@router.post("/")
def create_post(payload: dict, db: Session = Depends(get_db)):
    item = Post(**payload)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@router.delete("/{item_id}")
def delete_post(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Post).filter(Post.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}
