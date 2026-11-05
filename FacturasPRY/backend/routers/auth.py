from fastapi import APIRouter, HTTPException
from schemas.usuario import LoginSchema
from db.connection import get_connection
from auth.password import verify_password
from auth.jwt import create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])


def query_all(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@router.post("/login")
def login(data: LoginSchema):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM tb_Usuario WHERE Email = ?",
        (data.email,)
    )

    rows = query_all(cursor)
    conn.close()

    if not rows:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    usuario = rows[0]

    if not usuario.get("Activo"):
        raise HTTPException(status_code=401, detail="Usuario inactivo")

    if not verify_password(data.password, usuario["Contraseña"]):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    access_token = create_access_token(
        data={
            "sub": str(usuario["Id"]),
            "rol": usuario["IdRol"],
            "area": usuario["IdArea"]
        }
    )

    return {
        "success": True,
        "access_token": access_token,
        "user": {
            "id": usuario["Id"],
            "nombre": usuario["Nombre"],
            "email": usuario["Email"],
            "rol": usuario["IdRol"],
            "area": usuario["IdArea"]
        }
    }