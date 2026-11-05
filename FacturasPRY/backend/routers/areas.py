from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db.connection import get_connection
from auth.jwt import verify_token
from auth.permisos import validar_rol


router = APIRouter(
    prefix="/areas",
    tags=["Areas"]
)


# ============================================================
# SCHEMAS
# ============================================================

class AreaCreate(BaseModel):
    Nombre: str
    Descripcion: str = ""


class AreaUpdate(BaseModel):
    Nombre: str
    Descripcion: str = ""
    Activo: bool


# ============================================================
# OBTENER ÁREAS
# ============================================================

@router.get("/")
def get_areas(
    usuario_id: int = Depends(verify_token)
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                Id AS IdArea,
                Nombre,
                Descripcion,
                activo
            FROM tb_Area
            WHERE activo = -1
            ORDER BY Nombre
        """)

        columnas = [col[0] for col in cursor.description]

        areas = [
            dict(zip(columnas, fila))
            for fila in cursor.fetchall()
        ]

        return areas

    finally:

        cursor.close()
        conn.close()


# ============================================================
# CREAR ÁREA
# ============================================================

@router.post("/")
def create_area(
    area: AreaCreate,
    usuario_id: int = Depends(verify_token)
):

    validar_rol(usuario_id, 1)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO tb_Area
                (Nombre, Descripcion, activo)
            VALUES (?, ?, -1)
        """,
            area.Nombre,
            area.Descripcion
        )

        conn.commit()

        return {
            "message": "Área creada correctamente"
        }

    finally:

        cursor.close()
        conn.close()


# ============================================================
# ACTUALIZAR ÁREA
# ============================================================

@router.put("/{id_area}")
def update_area(
    id_area: int,
    area: AreaUpdate,
    usuario_id: int = Depends(verify_token)
):

    validar_rol(usuario_id, 1)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE tb_Area
            SET
                Nombre = ?,
                Descripcion = ?,
                activo = ?
            WHERE Id = ?
        """,
            area.Nombre,
            area.Descripcion,
            -1 if area.Activo else 0,
            id_area
        )

        conn.commit()

        return {
            "message": "Área actualizada correctamente"
        }

    finally:

        cursor.close()
        conn.close()


# ============================================================
# DESACTIVAR ÁREA
# ============================================================

@router.delete("/{id_area}")
def delete_area(
    id_area: int,
    usuario_id: int = Depends(verify_token)
):

    validar_rol(usuario_id, 1)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE tb_Area
            SET activo = 0
            WHERE Id = ?
        """,
            id_area
        )

        conn.commit()

        return {
            "message": "Área desactivada correctamente"
        }

    finally:

        cursor.close()
        conn.close()