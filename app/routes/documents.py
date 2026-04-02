import httpx
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..models import Cliente, Documento, TipoDocumento, EstadoDocumento
from ..schemas import DocumentoUploadResponse, TipoDocumentoEnum, DocumentoResponse
from ..auth import decodificar_token
from ..config import get_settings

router = APIRouter(prefix="/documentos", tags=["documentos"])
settings = get_settings()

def _extraer_qdrant_point_id(respuesta: object) -> Optional[str]:
    """
    Intenta extraer el point id de Qdrant desde una respuesta JSON de n8n.
    Soporta varias formas comunes (según cómo esté armado el workflow).
    """
    if not isinstance(respuesta, dict):
        return None

    # Formas directas
    for k in ("qdrant_point_id", "point_id", "pointId", "id"):
        v = respuesta.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v)

    # Formas anidadas comunes
    for path in (("result", "id"), ("result", "point_id"), ("result", "qdrant_point_id")):
        cur = respuesta
        ok = True
        for part in path:
            if not isinstance(cur, dict) or part not in cur:
                ok = False
                break
            cur = cur[part]
        if ok and isinstance(cur, (str, int)) and str(cur).strip():
            return str(cur)

    # Listas de ids (nos quedamos con el primero)
    for k in ("ids", "point_ids", "pointIds"):
        v = respuesta.get(k)
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, (str, int)) and str(first).strip():
                return str(first)

    return None


def get_current_cliente(authorization: str = Header(None), db: Session = Depends(get_db)) -> Cliente:
    """Dependency para obtener el cliente actual desde el token JWT"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no proporcionado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extraer token del header "Bearer <token>"
    try:
        token = authorization.replace("Bearer ", "")
    except AttributeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato de token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decodificar_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    cliente_id = int(payload.get("sub"))
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()

    if not cliente or not cliente.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cliente no encontrado o inactivo",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return cliente


@router.post("/upload", response_model=DocumentoUploadResponse)
async def upload_documento(
    file: UploadFile = File(..., description="Archivo PDF a cargar"),
    tipo: str = Form(..., description="Tipo de documento: 'tramite' o 'informacion'"),
    subcategoria: str = Form(..., description="Subcategoría del documento"),
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """
    Sube un PDF y lo envía al webhook de n8n para vectorización
    """
    # Validar tipo
    try:
        tipo_enum = TipoDocumentoEnum(tipo)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo inválido. Debe ser 'tramite' o 'informacion'",
        )

    # Validar que sea PDF
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos PDF",
        )

    # Leer contenido del PDF
    pdf_content = await file.read()

    # Crear registro en la base de datos
    documento = Documento(
        cliente_id=cliente.id,
        nombre_archivo=file.filename,
        tipo=tipo_enum.value,
        subcategoria=subcategoria,
        estado=EstadoDocumento.procesando,
    )
    db.add(documento)
    db.commit()
    db.refresh(documento)

    # Enviar a n8n (webhook)
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minutos timeout
            files = {"file": (file.filename, pdf_content, "application/pdf")}
            data = {
                "cliente_id": str(cliente.id),
                "collection": cliente.qdrant_collection,
                "tipo": tipo,
                "subcategoria": subcategoria,
                "documento_id": str(documento.id),
            }

            response = await client.post(
                settings.n8n_webhook_url,
                files=files,
                data=data,
            )

            # Actualizar estado según respuesta
            if response.status_code == 200:
                documento.estado = EstadoDocumento.completado
                documento.respuesta_n8n = response.json() if response.content else {}
                point_id = _extraer_qdrant_point_id(documento.respuesta_n8n)
                if point_id:
                    documento.qdrant_point_id = point_id
            else:
                documento.estado = EstadoDocumento.fallido
                documento.respuesta_n8n = {
                    "status_code": response.status_code,
                    "body": response.text,
                }

            db.commit()

            return DocumentoUploadResponse(
                mensaje="Documento procesado exitosamente",
                documento_id=documento.id,
                estado=documento.estado.value,
            )

    except httpx.TimeoutException:
        documento.estado = EstadoDocumento.fallido
        documento.respuesta_n8n = {"error": "Timeout: el procesamiento tardó más de 5 minutos"}
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="El procesamiento del documento excedió el tiempo límite. Contacte al administrador.",
        )
    except Exception as e:
        documento.estado = EstadoDocumento.fallido
        documento.respuesta_n8n = {"error": str(e)}
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al procesar el documento: {str(e)}",
        )


@router.get("/historial", response_model=list[DocumentoResponse])
def get_historial_documentos(
    db: Session = Depends(get_db),
    cliente: Cliente = Depends(get_current_cliente),
):
    """
    Obtiene el historial de documentos cargados por el cliente
    """
    documentos = (
        db.query(Documento)
        .filter(Documento.cliente_id == cliente.id)
        .order_by(Documento.created_at.desc())
        .all()
    )
    return documentos
