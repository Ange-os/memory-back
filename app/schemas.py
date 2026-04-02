from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TipoDocumentoEnum(str, Enum):
    tramite = "tramite"
    informacion = "informacion"


class EstadoDocumentoEnum(str, Enum):
    pendiente = "pendiente"
    procesando = "procesando"
    completado = "completado"
    fallido = "fallido"


# === Login ===
class LoginRequest(BaseModel):
    nombre_usuario: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    cliente_id: int
    nombre: str
    qdrant_collection: str


# === Cliente ===
class ClienteBase(BaseModel):
    nombre: str
    email: EmailStr
    qdrant_collection: str


class ClienteCreate(ClienteBase):
    password: str


class ClienteResponse(ClienteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    activo: bool
    created_at: datetime


# === Documento ===
class DocumentoCreate(BaseModel):
    nombre_archivo: str
    tipo: TipoDocumentoEnum
    subcategoria: str


class DocumentoResponse(DocumentoCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cliente_id: int
    qdrant_point_id: Optional[str] = None
    estado: EstadoDocumentoEnum
    created_at: datetime


class DocumentoUploadResponse(BaseModel):
    mensaje: str
    documento_id: int
    estado: str


# === Búsqueda ===
class BusquedaRequest(BaseModel):
    query: str
    limit: int = 10


class PuntoQdrant(BaseModel):
    id: str
    score: float
    payload: dict


class BusquedaResponse(BaseModel):
    resultados: List[PuntoQdrant]
    total: int


# === Colección Qdrant ===
class PuntoColeccion(BaseModel):
    id: str
    payload: dict


# === Puntos Qdrant ===
class PuntoUpdate(BaseModel):
    texto: Optional[str] = None
    tipo: Optional[str] = None
    subcategoria: Optional[str] = None
    metadata: Optional[dict] = None
