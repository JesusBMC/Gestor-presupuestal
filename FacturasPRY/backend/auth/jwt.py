import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.environ["JWT_SECRET_KEY"]  # falla explícito al arrancar si no está seteada
ALGORITHM = "HS256"

security = HTTPBearer()


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expirado o inválido")

    usuario_id = payload.get("sub")
    rol = payload.get("rol")
    area = payload.get("area")

    if usuario_id is None or rol is None:
        raise HTTPException(status_code=401, detail="Token inválido: faltan datos requeridos")

    return {
        "usuario_id": usuario_id,
        "rol": rol,
        "area": area
    }