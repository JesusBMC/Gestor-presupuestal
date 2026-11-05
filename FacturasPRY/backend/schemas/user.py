from pydantic import BaseModel

class UserCreate(BaseModel):
    nombre: str
    email: str
    password: str
    rol: int
    id_area: int
    activo: bool


class UserUpdate(BaseModel):
    nombre: str
    email: str
    rol: int
    id_area: int
    activo: bool