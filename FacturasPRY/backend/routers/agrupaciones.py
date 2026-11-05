from fastapi import APIRouter, Depends

from pydantic import BaseModel
 
from db.connection import get_connection

from auth.jwt import verify_token

from auth.permisos import validar_rol, validar_permiso_area
 
 
router = APIRouter(

    prefix="/agrupaciones",

    tags=["Agrupaciones"]

)
 
 
def query_all(cursor):

    columns = [col[0] for col in cursor.description]

    return [dict(zip(columns, row)) for row in cursor.fetchall()]
 
 
class AgrupacionCreate(BaseModel):

    IdArea: int

    Nombre: str
 
 
class AgrupacionUpdate(BaseModel):

    Nombre: str

    Activo: bool
 
 
# ============================================================

# 📥 GET - LISTAR AGRUPACIONES DE UN ÁREA

# ============================================================
 
@router.get("/{id_area}")

def get_agrupaciones(

    id_area: int,

    usuario_id: int = Depends(verify_token)

):

    validar_permiso_area(usuario_id, id_area)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        SELECT

            Id AS IdAgrupacion,

            IdArea,

            Nombre,

            Activo

        FROM tb_Agrupacion

        WHERE IdArea = ?

        ORDER BY Nombre

        """,

        (id_area,)

    )
 
    data = query_all(cursor)

    conn.close()
 
    return data
 
 
# ============================================================

# ➕ POST - CREAR AGRUPACIÓN (solo Admin)

# ============================================================
 
@router.post("/")

def create_agrupacion(

    agrupacion: AgrupacionCreate,

    usuario_id: int = Depends(verify_token)

):

    validar_rol(usuario_id, 1)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        INSERT INTO tb_Agrupacion

            (IdArea, Nombre, Activo)

        VALUES (?, ?, -1)

        """,

        (

            agrupacion.IdArea,

            agrupacion.Nombre

        )

    )
 
    conn.commit()

    conn.close()
 
    return {"message": "Agrupación creada correctamente"}
 
 
# ============================================================

# ✏️ PUT - EDITAR AGRUPACIÓN (solo Admin)

# ============================================================
 
@router.put("/{id_agrupacion}")

def update_agrupacion(

    id_agrupacion: int,

    agrupacion: AgrupacionUpdate,

    usuario_id: int = Depends(verify_token)

):

    validar_rol(usuario_id, 1)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        UPDATE tb_Agrupacion

        SET

            Nombre = ?,

            Activo = ?

        WHERE Id = ?

        """,

        (

            agrupacion.Nombre,

            -1 if agrupacion.Activo else 0,

            id_agrupacion

        )

    )
 
    conn.commit()

    conn.close()
 
    return {"message": "Agrupación actualizada correctamente"}
 
 
# ============================================================

# 🗑️ DELETE - DESACTIVAR AGRUPACIÓN (solo Admin)

# ============================================================
 
@router.delete("/{id_agrupacion}")

def delete_agrupacion(

    id_agrupacion: int,

    usuario_id: int = Depends(verify_token)

):

    validar_rol(usuario_id, 1)
 
    conn = get_connection()

    cursor = conn.cursor()
 
    cursor.execute(

        """

        UPDATE tb_Agrupacion

        SET Activo = 0

        WHERE Id = ?

        """,

        (id_agrupacion,)

    )
 
    conn.commit()

    conn.close()
 
    return {"message": "Agrupación desactivada correctamente"}
 