from pydantic import BaseModel
from typing import Optional


class LoginSchema(BaseModel):
    email: str
    password: str


class UsuarioCreate(BaseModel):
    Nombre: str
    IdRol: int
    Email: str
    Contraseña: str
    IdArea: Optional[int] = None
    Activo: bool = True