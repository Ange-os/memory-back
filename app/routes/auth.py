from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import timedelta
from ..database import get_db
from ..models import Cliente
from ..schemas import LoginRequest, Token
from ..auth import verificar_password, crear_access_token

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """
    Autentica un cliente y devuelve un token JWT
    """
    nombre = login_data.nombre_usuario.strip()
    if not nombre:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ingresá el nombre de usuario",
        )

    # Buscar cliente por nombre (sin distinguir mayúsculas/minúsculas)
    cliente = (
        db.query(Cliente)
        .filter(func.lower(Cliente.nombre) == func.lower(nombre))
        .first()
    )

    if not cliente or not verificar_password(login_data.password, cliente.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not cliente.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada. Contacte al administrador.",
        )

    # Crear token
    access_token = crear_access_token(
        data={"sub": str(cliente.id), "email": cliente.email},
        expires_delta=timedelta(minutes=1440),  # 24 horas
    )

    return Token(
        access_token=access_token,
        cliente_id=cliente.id,
        nombre=cliente.nombre,
        qdrant_collection=cliente.qdrant_collection,
    )
