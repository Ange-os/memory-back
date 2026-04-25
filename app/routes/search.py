from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
import logging
import httpx

from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Cliente
from ..schemas import (
    BloqueQdrantUpdate,
    BusquedaPayloadRequest,
    BusquedaPayloadResponse,
    BusquedaRequest,
    BusquedaResponse,
    PuntoColeccion,
    PuntoPayloadNormalizado,
    PuntoQdrant,
    PuntoUpdate,
)
from ..auth import decodificar_token
from ..config import get_settings

router = APIRouter(prefix="/search", tags=["búsqueda"])
settings = get_settings()
logger = logging.getLogger(__name__)


def get_current_cliente(authorization: str = Header(None), db: Session = Depends(get_db)) -> Cliente:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token no proporcionado", headers={"WWW-Authenticate": "Bearer"})
    try:
        token = authorization.replace("Bearer ", "")
    except AttributeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Formato de token inválido", headers={"WWW-Authenticate": "Bearer"})
    payload = decodificar_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado", headers={"WWW-Authenticate": "Bearer"})
    cliente_id = int(payload.get("sub"))
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente or not cliente.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cliente no encontrado o inactivo", headers={"WWW-Authenticate": "Bearer"})
    return cliente


def qdrant_headers() -> dict:
    return {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}


def qdrant_url(path: str) -> str:
    base = settings.qdrant_url.rstrip("/")
    return f"{base}{path}"


def _metadata(payload: dict) -> dict:
    meta = payload.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _extract_block_id(payload: dict) -> Optional[int]:
    meta = _metadata(payload)
    value = meta.get("block_id", payload.get("block_id"))
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_text(payload: dict) -> str:
    meta = _metadata(payload)
    return str(
        payload.get("content")
        or payload.get("texto")
        or meta.get("content")
        or meta.get("texto")
        or ""
    )


def _extract_tipo(payload: dict) -> str:
    meta = _metadata(payload)
    return str(payload.get("tipo") or payload.get("type") or meta.get("tipo") or meta.get("type") or "")


def _extract_subtopic(payload: dict) -> str:
    meta = _metadata(payload)
    return str(payload.get("subtopic") or payload.get("subcategoria") or meta.get("subtopic") or meta.get("subcategoria") or "")


def _extract_topic(payload: dict) -> str:
    meta = _metadata(payload)
    return str(payload.get("topic") or meta.get("topic") or "")


def _extract_title(payload: dict) -> str:
    meta = _metadata(payload)
    return str(payload.get("title") or meta.get("title") or "")


def _normalizar_punto(point: dict) -> PuntoPayloadNormalizado:
    payload = point.get("payload", {}) or {}
    return PuntoPayloadNormalizado(
        point_id=str(point.get("id")),
        block_id=_extract_block_id(payload),
        title=_extract_title(payload),
        topic=_extract_topic(payload),
        subtopic=_extract_subtopic(payload),
        tipo=_extract_tipo(payload),
        content=_extract_text(payload),
        payload=payload,
    )


def _match_field(text: str, field: str, punto: PuntoPayloadNormalizado) -> bool:
    if not text:
        return True
    haystack_map = {
        "title": punto.title,
        "topic": punto.topic,
        "subtopic": punto.subtopic,
        "type": punto.tipo,
        "content": punto.content,
    }
    if field in haystack_map:
        return text in haystack_map[field].lower()
    # Búsqueda libre sobre campos relevantes
    full = " ".join([punto.title, punto.topic, punto.subtopic, punto.tipo, punto.content]).lower()
    return text in full


@router.get("/puntos/{point_id}", response_model=PuntoColeccion)
def obtener_punto(
    point_id: str,
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Obtiene un punto específico de Qdrant (con payload)"""
    try:
        collection = cliente.qdrant_collection
        pid = int(point_id) if point_id.isdigit() else point_id

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/get"),
                headers=qdrant_headers(),
                json={"ids": [pid], "with_payload": True, "with_vector": False},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al obtener punto: {response.text}")

        result = response.json().get("result", [])
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Punto {point_id} no encontrado")

        p = result[0]
        return PuntoColeccion(id=str(p["id"]), payload=p.get("payload", {}) or {})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener punto: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al obtener punto: {str(e)}")


@router.get("/colecciones", response_model=List[PuntoColeccion])
def listar_colecciones(
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Lista los puntos en la colección del cliente"""
    try:
        collection = cliente.qdrant_collection

        with httpx.Client(timeout=30.0) as client:
            check = client.get(qdrant_url(f"/collections/{collection}"), headers=qdrant_headers())

        if check.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La colección '{collection}' no existe")
        if check.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error de Qdrant: {check.text}")

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/scroll"),
                headers=qdrant_headers(),
                json={"limit": 100, "with_payload": True, "with_vector": False},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al obtener puntos: {response.text}")

        puntos = response.json().get("result", {}).get("points", [])
        return [PuntoColeccion(id=str(p["id"]), payload=(p.get("payload", {}) or {})) for p in puntos]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al listar colección: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al listar colección: {str(e)}")


@router.post("/search", response_model=BusquedaResponse)
def buscar_en_coleccion(
    search_data: BusquedaRequest,
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Busca documentos en la colección Qdrant del cliente"""
    try:
        collection = cliente.qdrant_collection

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/scroll"),
                headers=qdrant_headers(),
                json={"limit": search_data.limit, "with_payload": True, "with_vector": False},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al buscar: {response.text}")

        resultados = response.json().get("result", {}).get("points", [])
        puntos = [PuntoQdrant(id=str(r["id"]), score=1.0, payload=r.get("payload", {})) for r in resultados]
        return BusquedaResponse(resultados=puntos, total=len(puntos))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al buscar en Qdrant: {str(e)}")


@router.post("/puntos/buscar", response_model=BusquedaPayloadResponse)
def buscar_puntos_payload(
    search_data: BusquedaPayloadRequest,
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Busca puntos por campos de payload (title/topic/subtopic/type/content)."""
    try:
        collection = cliente.qdrant_collection
        q = (search_data.q or "").strip().lower()
        field = (search_data.field or "").strip().lower() or "all"
        limit = max(1, min(search_data.limit, 500))

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/scroll"),
                headers=qdrant_headers(),
                json={"limit": 1000, "with_payload": True, "with_vector": False},
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al buscar puntos: {response.text}",
            )

        puntos = response.json().get("result", {}).get("points", [])
        normalizados = [_normalizar_punto(p) for p in puntos]
        filtrados = [p for p in normalizados if _match_field(q, field, p)]
        filtrados = filtrados[:limit]
        return BusquedaPayloadResponse(resultados=filtrados, total=len(filtrados))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al buscar en payload: {str(e)}",
        )


@router.put("/puntos/{point_id}")
def actualizar_punto(
    point_id: str,
    update_data: PuntoUpdate,
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Actualiza el payload de un punto en Qdrant"""
    try:
        collection = cliente.qdrant_collection
        pid = int(point_id) if point_id.isdigit() else point_id

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/scroll"),
                headers=qdrant_headers(),
                json={"filter": {"must": [{"has_id": [pid]}]}, "limit": 1, "with_payload": True, "with_vector": False},
            )

        puntos = response.json().get("result", {}).get("points", [])
        if not puntos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Punto {point_id} no encontrado")

        nuevo_payload = {**puntos[0].get("payload", {})}
        if update_data.texto is not None:
            nuevo_payload["texto"] = update_data.texto
            # Compatibilidad: en muchas ingestas el texto viene como "content"
            nuevo_payload["content"] = update_data.texto
        if update_data.tipo is not None:
            nuevo_payload["tipo"] = update_data.tipo
        if update_data.subcategoria is not None:
            nuevo_payload["subcategoria"] = update_data.subcategoria
        if update_data.metadata is not None:
            nuevo_payload = {**nuevo_payload, **update_data.metadata}

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/payload"),
                headers=qdrant_headers(),
                json={"payload": nuevo_payload, "points": [pid]},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al actualizar: {response.text}")

        return {"success": True, "message": "Punto actualizado", "id": point_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al actualizar punto: {str(e)}")


@router.delete("/puntos/{point_id}")
def eliminar_punto(
    point_id: str,
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Elimina un punto de Qdrant"""
    try:
        collection = cliente.qdrant_collection
        pid = int(point_id) if point_id.isdigit() else point_id

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/delete"),
                headers=qdrant_headers(),
                json={"points": [pid]},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al eliminar: {response.text}")

        return {"success": True, "message": "Punto eliminado", "id": point_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al eliminar punto: {str(e)}")


@router.put("/bloques/{block_id}")
def actualizar_bloque_por_block_id(
    block_id: int,
    update_data: BloqueQdrantUpdate,
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """Actualiza un punto en Qdrant usando metadata.block_id."""
    try:
        collection = cliente.qdrant_collection

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                qdrant_url(f"/collections/{collection}/points/scroll"),
                headers=qdrant_headers(),
                json={"limit": 1000, "with_payload": True, "with_vector": False},
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al buscar bloque: {response.text}",
            )

        puntos = response.json().get("result", {}).get("points", [])
        point = None
        for p in puntos:
            payload = p.get("payload", {}) or {}
            if _extract_block_id(payload) == block_id:
                point = p
                break

        if not point:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontro bloque con block_id={block_id}",
            )

        payload_actual: dict[str, Any] = {**(point.get("payload", {}) or {})}
        metadata_actual = _metadata(payload_actual)
        if update_data.content is not None:
            payload_actual["content"] = update_data.content
            payload_actual["texto"] = update_data.content
        if update_data.metadata is not None:
            payload_actual["metadata"] = {**metadata_actual, **update_data.metadata}

        pid = point.get("id")
        with httpx.Client(timeout=30.0) as client:
            update_response = client.post(
                qdrant_url(f"/collections/{collection}/points/payload"),
                headers=qdrant_headers(),
                json={"payload": payload_actual, "points": [pid]},
            )

        if update_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al actualizar bloque: {update_response.text}",
            )

        return {"success": True, "message": "Bloque actualizado", "block_id": block_id, "point_id": str(pid)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar bloque por block_id: {str(e)}",
        )