from fastapi import APIRouter, Depends

from pydantic import BaseModel
 
from db.connection import get_connection

from auth.jwt import verify_token

from auth.permisos import validar_rol, validar_permiso_area
 
 
router = APIRouter(

    prefix="/verticales",

    tags=["Verticales"]

)
 
 
def query_all(cursor):

    columns = [col[0] for col in cursor.description]

    return [dict(zip(columns, row)) for row in cursor.fetchall()]
 
 
class VerticalCreate(BaseModel):

    IdArea: int

    Nombre: str
 
 
class VerticalUpdate(BaseModel):

    Nombre: str

    Activo: bool
 
 
# ============================================================

# 📥 GET - LISTAR VERTICALES DE UN ÁREA

# ============================================================
 
@router.get("/{id_area}")

def get_verticales(

    id_area: int,

    usuario_id: int = Depends(verify_token)

):

    validar_permiso_area(usuario_id, id_area)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        SELECT

            Id AS IdVertical,

            IdArea,

            Nombre,

            Activo

        FROM tb_Vertical

        WHERE IdArea = ?

        ORDER BY Nombre

        """,

        (id_area,)

    )
 
    data = query_all(cursor)

    conn.close()
 
    return data
 
 
# ============================================================

# ➕ POST - CREAR VERTICAL (solo Admin)

# ============================================================
 
@router.post("/")

def create_vertical(

    vertical: VerticalCreate,

    usuario_id: int = Depends(verify_token)

):

    validar_rol(usuario_id, 1)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        INSERT INTO tb_Vertical

            (IdArea, Nombre, Activo)

        VALUES (?, ?, -1)

        """,

        (

            vertical.IdArea,

            vertical.Nombre

        )

    )
 
    conn.commit()

    conn.close()
 
    return {"message": "Vertical creada correctamente"}
 
 
# ============================================================

# ✏️ PUT - EDITAR VERTICAL (solo Admin)

# ============================================================
 
@router.put("/{id_vertical}")

def update_vertical(

    id_vertical: int,

    vertical: VerticalUpdate,

    usuario_id: int = Depends(verify_token)

):

    validar_rol(usuario_id, 1)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        UPDATE tb_Vertical

        SET

            Nombre = ?,

            Activo = ?

        WHERE Id = ?

        """,

        (

            vertical.Nombre,

            -1 if vertical.Activo else 0,

            id_vertical

        )

    )
 
    conn.commit()

    conn.close()
 
    return {"message": "Vertical actualizada correctamente"}
 
 
# ============================================================

# 🗑️ DELETE - DESACTIVAR VERTICAL (solo Admin)

# ============================================================
 
@router.delete("/{id_vertical}")

def delete_vertical(

    id_vertical: int,

    usuario_id: int = Depends(verify_token)

):

    validar_rol(usuario_id, 1)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        UPDATE tb_Vertical

        SET Activo = 0

        WHERE Id = ?

        """,

        (id_vertical,)

    )
 
    conn.commit()

    conn.close()
 
    return {"message": "Vertical desactivada correctamente"}
 