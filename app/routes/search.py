from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Header
import logging
import httpx

from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Cliente
from ..schemas import BusquedaRequest, BusquedaResponse, PuntoQdrant, PuntoUpdate, PuntoColeccion
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