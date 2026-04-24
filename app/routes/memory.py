from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..memory_database import get_memory_db
from .documents import get_current_cliente
from ..models import Cliente

router = APIRouter(prefix="/memory", tags=["memory"])


class TopicCreate(BaseModel):
    name: str
    description: Optional[str] = None


class SubtopicCreate(BaseModel):
    topic_id: int
    name: str
    description: Optional[str] = None


class BlockCreate(BaseModel):
    subtopic_id: int
    title: str = ""
    content: str = ""
    content_type: str = "text"


class BlockUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    content_type: Optional[str] = None
    order_index: Optional[int] = None


@router.get("/topics")
def get_topics(
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    rows = db.execute(text("SELECT id, name, description FROM topics ORDER BY id")).mappings().all()
    return [dict(row) for row in rows]


@router.post("/topics")
def create_topic(
    payload: TopicCreate,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name required")

    db.execute(
        text("INSERT INTO topics (name, description) VALUES (:name, :description)"),
        {"name": payload.name.strip(), "description": payload.description},
    )
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().first()["id"]
    return {"id": new_id, "name": payload.name.strip(), "description": payload.description}


@router.delete("/topics/{topic_id}")
def delete_topic(
    topic_id: int,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    db.execute(text("DELETE FROM topics WHERE id = :id"), {"id": topic_id})
    db.commit()
    return {"success": True}


@router.get("/topics/{topic_id}/subtopics")
def get_subtopics(
    topic_id: int,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    rows = db.execute(
        text(
            "SELECT id, topic_id, name, description, order_index "
            "FROM subtopics WHERE topic_id = :topic_id ORDER BY order_index, id"
        ),
        {"topic_id": topic_id},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/subtopics")
def create_subtopic(
    payload: SubtopicCreate,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name required")

    db.execute(
        text(
            "INSERT INTO subtopics (topic_id, name, description, order_index) "
            "VALUES (:topic_id, :name, :description, 0)"
        ),
        {
            "topic_id": payload.topic_id,
            "name": payload.name.strip(),
            "description": payload.description,
        },
    )
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().first()["id"]
    return {
        "id": new_id,
        "topic_id": payload.topic_id,
        "name": payload.name.strip(),
        "description": payload.description,
        "order_index": 0,
    }


@router.delete("/subtopics/{subtopic_id}")
def delete_subtopic(
    subtopic_id: int,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    db.execute(text("DELETE FROM subtopics WHERE id = :id"), {"id": subtopic_id})
    db.commit()
    return {"success": True}


@router.get("/subtopics/{subtopic_id}/content")
def get_content_blocks(
    subtopic_id: int,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    rows = db.execute(
        text(
            "SELECT id, subtopic_id, title, content, content_type, order_index, version "
            "FROM content_blocks "
            "WHERE subtopic_id = :subtopic_id AND is_active = 1 "
            "ORDER BY order_index, id"
        ),
        {"subtopic_id": subtopic_id},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/content")
def create_content_block(
    payload: BlockCreate,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    db.execute(
        text(
            "INSERT INTO content_blocks (subtopic_id, title, content, content_type, order_index, version) "
            "VALUES (:subtopic_id, :title, :content, :content_type, 0, 1)"
        ),
        {
            "subtopic_id": payload.subtopic_id,
            "title": payload.title or "",
            "content": payload.content or "",
            "content_type": payload.content_type or "text",
        },
    )
    db.commit()
    new_id = db.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().first()["id"]
    return {
        "id": new_id,
        "subtopic_id": payload.subtopic_id,
        "title": payload.title or "",
        "content": payload.content or "",
        "content_type": payload.content_type or "text",
        "order_index": 0,
        "version": 1,
    }


@router.put("/content/{block_id}")
def update_content_block(
    block_id: int,
    payload: BlockUpdate,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    current = db.execute(
        text("SELECT title, content, content_type, order_index, version FROM content_blocks WHERE id = :id"),
        {"id": block_id},
    ).mappings().first()

    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bloque no encontrado")

    new_version = int(current["version"] or 0) + 1
    db.execute(
        text(
            "UPDATE content_blocks SET "
            "title = :title, content = :content, content_type = :content_type, "
            "order_index = :order_index, version = :version, updated_at = NOW() "
            "WHERE id = :id"
        ),
        {
            "id": block_id,
            "title": current["title"] if payload.title is None else payload.title,
            "content": current["content"] if payload.content is None else payload.content,
            "content_type": current["content_type"] if payload.content_type is None else payload.content_type,
            "order_index": current["order_index"] if payload.order_index is None else payload.order_index,
            "version": new_version,
        },
    )
    db.commit()
    return {"success": True, "version": new_version}


@router.delete("/content/{block_id}")
def delete_content_block(
    block_id: int,
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    db.execute(
        text("UPDATE content_blocks SET is_active = 0, updated_at = NOW() WHERE id = :id"),
        {"id": block_id},
    )
    db.commit()
    return {"success": True}


@router.get("/export/json")
def export_json(
    db: Session = Depends(get_memory_db),
    _: Cliente = Depends(get_current_cliente),
):
    topics = db.execute(text("SELECT id, name, description FROM topics ORDER BY id")).mappings().all()
    result: list[dict[str, Any]] = []

    for topic in topics:
        subtopics = db.execute(
            text(
                "SELECT id, name, description FROM subtopics "
                "WHERE topic_id = :topic_id ORDER BY order_index, id"
            ),
            {"topic_id": topic["id"]},
        ).mappings().all()

        subtopics_data = []
        for subtopic in subtopics:
            blocks = db.execute(
                text(
                    "SELECT id, title, content, content_type FROM content_blocks "
                    "WHERE subtopic_id = :subtopic_id AND is_active = 1 "
                    "ORDER BY order_index, id"
                ),
                {"subtopic_id": subtopic["id"]},
            ).mappings().all()

            subtopics_data.append(
                {
                    "name": subtopic["name"],
                    "description": subtopic["description"],
                    "blocks": [
                        {
                            "id": b["id"],
                            "title": b["title"],
                            "content": b["content"],
                            "type": b["content_type"],
                        }
                        for b in blocks
                    ],
                }
            )

        result.append(
            {
                "name": topic["name"],
                "description": topic["description"],
                "subtopics": subtopics_data,
            }
        )

    return {"topics": result, "exportedAt": datetime.utcnow().isoformat() + "Z"}
