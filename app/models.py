from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import enum


class TipoDocumento(str, enum.Enum):
    tramite = "tramite"
    informacion = "informacion"


class EstadoDocumento(str, enum.Enum):
    pendiente = "pendiente"
    procesando = "procesando"
    completado = "completado"
    fallido = "fallido"


class Cliente(Base):
    __tablename__ = "qdrant_forms_clientes"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    qdrant_collection = Column(String(100), unique=True, nullable=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    documentos = relationship("Documento", back_populates="cliente", cascade="all, delete-orphan")


class Documento(Base):
    __tablename__ = "qdrant_forms_documentos"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("qdrant_forms_clientes.id", ondelete="CASCADE"), nullable=False)
    nombre_archivo = Column(String(255), nullable=False)
    tipo = Column(Enum(TipoDocumento), nullable=False)
    subcategoria = Column(String(100), nullable=False)
    qdrant_point_id = Column(String(100), nullable=True)
    estado = Column(Enum(EstadoDocumento), default=EstadoDocumento.pendiente)
    respuesta_n8n = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cliente = relationship("Cliente", back_populates="documentos")
