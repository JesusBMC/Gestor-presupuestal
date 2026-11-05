from fastapi import APIRouter, HTTPException, Depends
from passlib.context import CryptContext

from schemas.usuario import UsuarioCreate
from db.connection import get_connection
from auth.jwt import verify_token
from auth.permisos import validar_rol


router = APIRouter(
    prefix="/usuarios",
    tags=["Usuarios"]
)

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# ============================================================
# OBTENER ROLES
# ============================================================

@router.get("/roles")
def obtener_roles(
    usuario_id: int = Depends(verify_token)
):

    validar_rol(usuario_id, 1)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                IdRol,
                NombreRol
            FROM tb_Roles
            ORDER BY IdRol
        """)

        filas = cursor.fetchall()

        return [
            {
                "IdRol": fila.IdRol,
                "NombreRol": fila.NombreRol
            }
            for fila in filas
        ]

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo roles: {str(e)}"
        )

    finally:

        cursor.close()
        conn.close()


# ============================================================
# CREAR USUARIO
# ============================================================

@router.post("")
def crear_usuario(
    usuario: UsuarioCreate,
    usuario_id: int = Depends(verify_token)
):

    validar_rol(usuario_id, 1)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # ----------------------------------------------------
        # VALIDAR CORREO
        # ----------------------------------------------------

        email = usuario.Email.strip().lower()

        if not email.endswith("@bolsamercantil.com.co"):

            raise HTTPException(
                status_code=400,
                detail="El correo debe pertenecer a @bolsamercantil.com.co"
            )

        # ----------------------------------------------------
        # VALIDAR CORREO DUPLICADO
        # ----------------------------------------------------

        cursor.execute("""
            SELECT Id
            FROM tb_Usuario
            WHERE Email = ?
        """, email)

        if cursor.fetchone():

            raise HTTPException(
                status_code=400,
                detail="Ya existe un usuario con ese correo."
            )

        # ----------------------------------------------------
        # VALIDAR ROL
        # ----------------------------------------------------

        cursor.execute("""
            SELECT IdRol
            FROM tb_Roles
            WHERE IdRol = ?
        """, usuario.IdRol)

        if not cursor.fetchone():

            raise HTTPException(
                status_code=400,
                detail="El rol seleccionado no existe."
            )

        # ----------------------------------------------------
        # VALIDAR ÁREA
        # ----------------------------------------------------

        if usuario.IdArea is not None:

            cursor.execute("""
                SELECT Id
                FROM tb_Area
                WHERE Id = ?
                  AND activo = -1
            """, usuario.IdArea)

            if not cursor.fetchone():

                raise HTTPException(
                    status_code=400,
                    detail="El área seleccionada no existe o está inactiva."
                )

        # ----------------------------------------------------
        # HASH
        # ----------------------------------------------------

        password_hash = pwd_context.hash(
            usuario.Contraseña
        )

        # ----------------------------------------------------
        # INSERTAR
        # ----------------------------------------------------

        cursor.execute("""
            INSERT INTO tb_Usuario
            (
                Nombre,
                IdRol,
                Email,
                Contraseña,
                IdArea,
                Activo
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            usuario.Nombre.strip(),
            usuario.IdRol,
            email,
            password_hash,
            usuario.IdArea,
            -1 if usuario.Activo else 0
        )

        conn.commit()

        return {
            "success": True,
            "message": "Usuario creado correctamente."
        }

    except HTTPException:

        raise

    except Exception as e:

        conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Error creando usuario: {str(e)}"
        )

    finally:

        cursor.close()
        conn.close()