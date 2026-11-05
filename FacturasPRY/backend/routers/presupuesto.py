from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional

from db.connection import get_connection
from auth.jwt import verify_token
from auth.permisos import validar_rol, validar_permiso_area


router = APIRouter(
    prefix="/presupuesto",
    tags=["Presupuesto"]
)


def query_all(cursor):
    columns = [col[0] for col in cursor.description]
    rows = []
    for row in cursor.fetchall():
        rows.append({
            col: (float(val) if isinstance(val, Decimal) else val)
            for col, val in zip(columns, row)
        })
    return rows


def query_one(cursor):
    columns = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    if not row:
        return None
    return {
        col: (float(val) if isinstance(val, Decimal) else val)
        for col, val in zip(columns, row)
    }


class PresupuestoGeneralCreate(BaseModel):
    IdArea: int
    Ano: int
    MontoAsignado: float


class PresupuestoMensualCreate(BaseModel):
    IdArea: int
    Ano: int
    Mes: int
    MontoAsignado: float


class PresupuestoUpdate(BaseModel):
    MontoAsignado: float


# ============================================================
# NUEVO - PRESUPUESTO POR TIPO (OPEX / CAPEX), cuelga del General
# ============================================================

class PresupuestoTipoCreate(BaseModel):
    IdArea: int
    Ano: int
    Tipo: str  # 'OPEX' o 'CAPEX'
    MontoAsignado: float


TIPOS_VALIDOS = ("OPEX", "CAPEX")


# ============================================================
# 🧠 HELPER - Validar contra el presupuesto GENERAL del área/año
# ============================================================
# SIN CAMBIOS. Se reutiliza tal cual para validar OPEX/CAPEX ≤ General,
# igual que hoy se usa para validar Mensual ≤ General.

def validar_no_supera_general(
    cursor,
    id_area: int,
    ano: int,
    monto_nuevo: float,
    id_presupuesto_excluir: int = None
):
    cursor.execute(
        """
        SELECT Id, MontoAsignado
        FROM tb_Presupuesto
        WHERE IdArea = ? AND Ano = ? AND Tipo = 'General'
        """,
        (id_area, ano)
    )
    row = cursor.fetchone()

    if not row:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El área no tiene un presupuesto general definido para el año {ano}. "
                f"Créalo antes de asignar meses."
            )
        )

    id_general, presupuesto_general = row
    presupuesto_general = float(presupuesto_general) if presupuesto_general else 0.0

    if id_presupuesto_excluir:
        cursor.execute(
            """
            SELECT SUM(MontoAsignado)
            FROM tb_Presupuesto
            WHERE IdPresupuestoPadre = ? AND Id <> ?
            """,
            (id_general, id_presupuesto_excluir)
        )
    else:
        cursor.execute(
            """
            SELECT SUM(MontoAsignado)
            FROM tb_Presupuesto
            WHERE IdPresupuestoPadre = ?
            """,
            (id_general,)
        )

    row_suma = cursor.fetchone()
    suma_actual = float(row_suma[0]) if row_suma and row_suma[0] else 0.0

    if (suma_actual + monto_nuevo) > presupuesto_general:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La suma de los hijos del general ({suma_actual + monto_nuevo:,.0f}) "
                f"superaría el presupuesto general del área ({presupuesto_general:,.0f})"
            )
        )

    return id_general


# ============================================================
# 🧠 HELPER NUEVO - Validar proyección mensual Tipo contra su
# presupuesto anual OPEX/CAPEX (mismo patrón que validar_no_supera_general,
# pero la "suma de hijos" sale de tb_ProyeccionGasto en vez de IdPresupuestoPadre)
# ============================================================

def validar_no_supera_presupuesto_tipo(cursor, id_area: int, ano: int, tipo: str, filas):
    """
    filas: lista de objetos con .MontoProyectado y .Tipo (ya filtrados o no por tipo,
    esta función filtra internamente por `tipo`).
    """
    cursor.execute(
        """
        SELECT MontoAsignado
        FROM tb_Presupuesto
        WHERE IdArea = ? AND Ano = ? AND Tipo = ?
        """,
        (id_area, ano, tipo)
    )
    row = cursor.fetchone()

    if not row:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El área no tiene un presupuesto {tipo} definido para el año {ano}. "
                f"Créalo antes de proyectar."
            )
        )

    presupuesto_tipo = float(row[0]) if row[0] else 0.0

    suma_nueva = sum(f.MontoProyectado for f in filas if f.Tipo == tipo)

    if suma_nueva > presupuesto_tipo:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La proyección total de {tipo} ({suma_nueva:,.0f}) "
                f"superaría el presupuesto {tipo} asignado ({presupuesto_tipo:,.0f})"
            )
        )


# ============================================================
# 📌 GET - PRESUPUESTO GENERAL DE UN ÁREA/AÑO
# ============================================================

@router.get("/general/{id_area}")
def get_presupuesto_general(
    id_area: int,
    ano: int,
    user: dict = Depends(verify_token)
):
    validar_permiso_area(user, id_area)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT Id, IdArea, Ano, MontoAsignado, activo
        FROM tb_Presupuesto
        WHERE IdArea = ? AND Ano = ? AND Tipo = 'General'
        """,
        (id_area, ano)
    )

    data = query_one(cursor)
    conn.close()

    return data


# ============================================================
# ➕ POST - CREAR O ACTUALIZAR PRESUPUESTO GENERAL (upsert)
# ============================================================

@router.post("/general")
def crear_o_actualizar_general(
    presupuesto: PresupuestoGeneralCreate,
    user: dict = Depends(verify_token)
):
    validar_rol(user, 2)  # Gestor (Admin pasa siempre)
    validar_permiso_area(user, presupuesto.IdArea)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT Id FROM tb_Presupuesto
        WHERE IdArea = ? AND Ano = ? AND Tipo = 'General'
        """,
        (presupuesto.IdArea, presupuesto.Ano)
    )
    row = cursor.fetchone()

    if row:
        id_general = row[0]
        cursor.execute(
            "UPDATE tb_Presupuesto SET MontoAsignado = ? WHERE Id = ?",
            (presupuesto.MontoAsignado, id_general)
        )
        mensaje = "Presupuesto general actualizado correctamente"
    else:
        cursor.execute(
            """
            INSERT INTO tb_Presupuesto
                (IdArea, Ano, Tipo, MontoAsignado, activo)
            VALUES (?, ?, 'General', ?, True)
            """,
            (presupuesto.IdArea, presupuesto.Ano, presupuesto.MontoAsignado)
        )
        mensaje = "Presupuesto general creado correctamente"

    conn.commit()
    conn.close()

    return {"message": mensaje}


# ============================================================
# 📥 GET - PRESUPUESTO OPEX/CAPEX DE UN ÁREA/AÑO (NUEVO)
# ============================================================
# Devuelve las filas hijas del General con Tipo IN ('OPEX','CAPEX').
# Puede no existir ninguna, una, o las dos -> el front decide qué mostrar.

@router.get("/tipo/{id_area}")
def get_presupuesto_tipo(
    id_area: int,
    ano: int,
    user: dict = Depends(verify_token)
):
    validar_permiso_area(user, id_area)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT Id, IdArea, Ano, Tipo, MontoAsignado, IdPresupuestoPadre, activo
        FROM tb_Presupuesto
        WHERE IdArea = ? AND Ano = ? AND Tipo IN ('OPEX', 'CAPEX')
        """,
        (id_area, ano)
    )

    data = query_all(cursor)
    conn.close()

    return data


# ============================================================
# ➕ POST - CREAR O ACTUALIZAR PRESUPUESTO OPEX/CAPEX (upsert, NUEVO)
# ============================================================
# Reutiliza validar_no_supera_general sin cambios: valida que
# OPEX + CAPEX (+ lo que quede de Mensual legado, si lo hubiera) no
# superen el General. Mismo patrón que el Mensual de siempre.

@router.post("/tipo")
def crear_o_actualizar_tipo(
    presupuesto: PresupuestoTipoCreate,
    user: dict = Depends(verify_token)
):
    validar_rol(user, 2)
    validar_permiso_area(user, presupuesto.IdArea)

    if presupuesto.Tipo not in TIPOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Tipo debe ser 'OPEX' o 'CAPEX'")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT Id FROM tb_Presupuesto
        WHERE IdArea = ? AND Ano = ? AND Tipo = ?
        """,
        (presupuesto.IdArea, presupuesto.Ano, presupuesto.Tipo)
    )
    row = cursor.fetchone()
    id_excluir = row[0] if row else None

    id_general = validar_no_supera_general(
        cursor,
        presupuesto.IdArea,
        presupuesto.Ano,
        presupuesto.MontoAsignado,
        id_presupuesto_excluir=id_excluir
    )

    if row:
        id_tipo = row[0]
        cursor.execute(
            "UPDATE tb_Presupuesto SET MontoAsignado = ? WHERE Id = ?",
            (presupuesto.MontoAsignado, id_tipo)
        )
        mensaje = f"Presupuesto {presupuesto.Tipo} actualizado correctamente"
    else:
        cursor.execute(
            """
            INSERT INTO tb_Presupuesto
                (IdArea, Ano, Tipo, MontoAsignado, IdPresupuestoPadre, activo)
            VALUES (?, ?, ?, ?, ?, True)
            """,
            (presupuesto.IdArea, presupuesto.Ano, presupuesto.Tipo, presupuesto.MontoAsignado, id_general)
        )
        mensaje = f"Presupuesto {presupuesto.Tipo} creado correctamente"

    conn.commit()
    conn.close()

    return {"message": mensaje}


# ============================================================
# 📥 GET - LISTAR PRESUPUESTOS MENSUALES DE UN ÁREA
# ============================================================
# SIN CAMBIOS. Se deja de generar Tipo='Mensual' hacia adelante, pero
# esta lectura sigue funcionando igual para lo que ya exista en Access.

@router.get("/{id_area}")
def get_presupuesto(
    id_area: int,
    ano: int = None,
    user: dict = Depends(verify_token)
):
    validar_permiso_area(user, id_area)

    conn = get_connection()
    cursor = conn.cursor()

    if ano:
        cursor.execute(
            """
            SELECT Id, IdArea, Ano, Mes, MontoAsignado, IdPresupuestoPadre
            FROM tb_Presupuesto
            WHERE IdArea = ? AND Ano = ? AND Tipo = 'Mensual'
            ORDER BY Mes
            """,
            (id_area, ano)
        )
    else:
        cursor.execute(
            """
            SELECT Id, IdArea, Ano, Mes, MontoAsignado, IdPresupuestoPadre
            FROM tb_Presupuesto
            WHERE IdArea = ? AND Tipo = 'Mensual'
            ORDER BY Ano DESC, Mes
            """,
            (id_area,)
        )

    data = query_all(cursor)
    conn.close()

    return data


# ============================================================
# ➕ POST - CREAR PRESUPUESTO MENSUAL
# ============================================================
# SIN CAMBIOS DE LÓGICA. Simplemente ya no se llama desde el front
# nuevo, pero el endpoint queda intacto por si algo legado lo usa.

@router.post("/")
def create_presupuesto(
    presupuesto: PresupuestoMensualCreate,
    user: dict = Depends(verify_token)
):
    validar_rol(user, 2)
    validar_permiso_area(user, presupuesto.IdArea)

    conn = get_connection()
    cursor = conn.cursor()

    id_general = validar_no_supera_general(
        cursor,
        presupuesto.IdArea,
        presupuesto.Ano,
        presupuesto.MontoAsignado
    )

    cursor.execute(
        """
        INSERT INTO tb_Presupuesto
            (IdArea, Ano, Mes, MontoAsignado, Tipo, IdPresupuestoPadre, activo)
        VALUES (?, ?, ?, ?, 'Mensual', ?, True)
        """,
        (
            presupuesto.IdArea,
            presupuesto.Ano,
            presupuesto.Mes,
            presupuesto.MontoAsignado,
            id_general
        )
    )

    conn.commit()
    conn.close()

    return {"message": "Presupuesto mensual creado correctamente"}


# ============================================================
# ✏️ PUT - EDITAR PRESUPUESTO MENSUAL
# ============================================================
# SIN CAMBIOS.

@router.put("/{id_presupuesto}")
def update_presupuesto(
    id_presupuesto: int,
    presupuesto: PresupuestoUpdate,
    user: dict = Depends(verify_token)
):
    validar_rol(user, 2)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT IdArea, Ano FROM tb_Presupuesto WHERE Id = ? AND Tipo = 'Mensual'",
        (id_presupuesto,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Presupuesto mensual no encontrado")

    id_area, ano = row

    validar_permiso_area(user, id_area)

    validar_no_supera_general(
        cursor,
        id_area,
        ano,
        presupuesto.MontoAsignado,
        id_presupuesto_excluir=id_presupuesto
    )

    cursor.execute(
        """
        UPDATE tb_Presupuesto
        SET MontoAsignado = ?
        WHERE Id = ?
        """,
        (presupuesto.MontoAsignado, id_presupuesto)
    )

    conn.commit()
    conn.close()

    return {"message": "Presupuesto mensual actualizado correctamente"}


# ============================================================
# 🗑️ DELETE - ELIMINAR PRESUPUESTO (general, mensual, OPEX o CAPEX)
# ============================================================
# SIN CAMBIOS DE LÓGICA: como OPEX/CAPEX cuelgan de IdPresupuestoPadre
# igual que antes Mensual, el bloqueo de "no eliminar el General con
# hijos" ya protege también a OPEX/CAPEX sin tocar nada aquí.

@router.delete("/{id_presupuesto}")
def delete_presupuesto(
    id_presupuesto: int,
    user: dict = Depends(verify_token)
):
    validar_rol(user, 2)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT IdArea, Tipo FROM tb_Presupuesto WHERE Id = ?",
        (id_presupuesto,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Presupuesto no encontrado")

    id_area, tipo = row

    validar_permiso_area(user, id_area)

    if tipo == "General":
        cursor.execute(
            "SELECT COUNT(*) FROM tb_Presupuesto WHERE IdPresupuestoPadre = ?",
            (id_presupuesto,)
        )
        hijos = cursor.fetchone()[0]
        if hijos > 0:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="No se puede eliminar el presupuesto general mientras tenga meses u OPEX/CAPEX asignados"
            )

    cursor.execute(
        "DELETE FROM tb_Presupuesto WHERE Id = ?",
        (id_presupuesto,)
    )

    conn.commit()
    conn.close()

    return {"message": "Presupuesto eliminado correctamente"}


# ============================================================
# PROYECCIÓN DE GASTOS (tb_ProyeccionGasto)
# ============================================================
# tb_ProyeccionGasto ahora tiene columnas Tipo (nullable) e
# IdAgrupacion (nullable). Cada fila es una cosa o la otra:
#   - Celda de Agrupación -> IdAgrupacion con valor, Tipo = NULL
#   - Celda de Tipo        -> Tipo = 'OPEX'/'CAPEX', IdAgrupacion = NULL
# Se manejan con DOS endpoints batch separados para que la limpieza
# (DELETE de lo que ya no viene en el payload) de una matriz no borre
# la otra.

class ProyeccionGastoRow(BaseModel):
    """Una celda de la matriz de Agrupación: (Mes, Agrupación, Vertical opcional)"""
    IdArea: int
    Ano: int
    Mes: int
    IdAgrupacion: int
    IdVertical: Optional[int] = None
    MontoProyectado: float


class ProyeccionGastoBatch(BaseModel):
    """Payload para guardar toda la matriz de Agrupación de una vez"""
    IdArea: int
    Ano: int
    datos: list[ProyeccionGastoRow]


class ProyeccionTipoGastoRow(BaseModel):
    """Una celda de la matriz de Tipo (OPEX/CAPEX): (Mes, Tipo)"""
    IdArea: int
    Ano: int
    Mes: int
    Tipo: str  # 'OPEX' o 'CAPEX'
    IdVertical: Optional[int] = None
    MontoProyectado: float


class ProyeccionTipoGastoBatch(BaseModel):
    """Payload para guardar toda la matriz de Tipo de una vez"""
    IdArea: int
    Ano: int
    datos: list[ProyeccionTipoGastoRow]


# ============================================================
# 📥 GET - OBTENER MATRIZ COMPLETA DE PROYECCIONES
# (Agrupación + Tipo, el front separa por IdAgrupacion/Tipo)
# ============================================================

@router.get("/proyeccion/{id_area}")
def get_proyeccion_gasto(
    id_area: int,
    ano: int,
    user: dict = Depends(verify_token)
):
    """
    Retorna TODAS las filas de proyección del área/año, mezclando las
    dos matrices. Cada fila trae Tipo para que el front sepa a cuál
    matriz pertenece:
        - Tipo is None  -> celda de Agrupación (usa IdAgrupacion)
        - Tipo is not None -> celda de Tipo OPEX/CAPEX (IdAgrupacion es None)
    """
    validar_permiso_area(user, id_area)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT Id, IdArea, Ano, Mes, IdAgrupacion, IdVertical, Tipo, MontoProyectado, FechaActualizacion
        FROM tb_ProyeccionGasto
        WHERE IdArea = ? AND Ano = ?
        ORDER BY Mes, IdAgrupacion
        """,
        (id_area, ano)
    )

    data = query_all(cursor)
    conn.close()

    return data


# ============================================================
# ➕ POST - GUARDAR MATRIZ DE AGRUPACIÓN (BATCH) - existente,
# ajustado para no tocar las filas de Tipo (IdAgrupacion IS NULL)
# ============================================================

@router.post("/proyeccion/batch")
def guardar_proyeccion_batch(
    payload: ProyeccionGastoBatch,
    user: dict = Depends(verify_token)
):
    """
    Guarda todas las celdas de la matriz de Agrupación de una sola vez.
    Solo lee/escribe/borra filas donde IdAgrupacion IS NOT NULL (Tipo NULL),
    así nunca toca las celdas de la matriz OPEX/CAPEX que vive en la
    misma tabla.
    """
    validar_rol(user, 2)
    validar_permiso_area(user, payload.IdArea)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT Id, Mes, IdAgrupacion, IdVertical
            FROM tb_ProyeccionGasto
            WHERE IdArea = ? AND Ano = ? AND IdAgrupacion IS NOT NULL
            """,
            (payload.IdArea, payload.Ano)
        )
        registros_actuales = {}
        for row in cursor.fetchall():
            key = (row[1], row[2], row[3])  # (Mes, IdAgrupacion, IdVertical)
            registros_actuales[key] = row[0]

        inserted = 0
        updated = 0
        datos_nuevos_keys = set()

        for fila in payload.datos:
            key = (fila.Mes, fila.IdAgrupacion, fila.IdVertical)
            datos_nuevos_keys.add(key)

            if key in registros_actuales:
                cursor.execute(
                    """
                    UPDATE tb_ProyeccionGasto
                    SET MontoProyectado = ?, FechaActualizacion = ?
                    WHERE Id = ?
                    """,
                    (fila.MontoProyectado, datetime.now(), registros_actuales[key])
                )
                updated += 1
            else:
                cursor.execute(
                    """
                    INSERT INTO tb_ProyeccionGasto
                        (IdArea, Ano, Mes, IdAgrupacion, IdVertical, Tipo, MontoProyectado, FechaActualizacion)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        payload.IdArea,
                        payload.Ano,
                        fila.Mes,
                        fila.IdAgrupacion,
                        fila.IdVertical,
                        fila.MontoProyectado,
                        datetime.now()
                    )
                )
                inserted += 1

        deleted = 0
        for key, id_registro in registros_actuales.items():
            if key not in datos_nuevos_keys:
                cursor.execute("DELETE FROM tb_ProyeccionGasto WHERE Id = ?", (id_registro,))
                deleted += 1

        conn.commit()
        conn.close()

        return {
            "message": "Proyecciones guardadas exitosamente",
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted
        }

    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error al guardar proyecciones: {str(e)}")


# ============================================================
# ➕ POST - GUARDAR MATRIZ DE TIPO OPEX/CAPEX (BATCH) - NUEVO
# ============================================================

@router.post("/proyeccion-tipo/batch")
def guardar_proyeccion_tipo_batch(
    payload: ProyeccionTipoGastoBatch,
    user: dict = Depends(verify_token)
):
    """
    Guarda todas las celdas de la matriz Mes x Tipo (OPEX/CAPEX) de una
    sola vez. Solo lee/escribe/borra filas donde Tipo IS NOT NULL
    (IdAgrupacion NULL), así nunca toca las celdas de la matriz de
    Agrupación que vive en la misma tabla.

    Valida antes de guardar que la suma proyectada de cada Tipo no
    supere el presupuesto anual asignado a ese Tipo (tb_Presupuesto).
    """
    validar_rol(user, 2)
    validar_permiso_area(user, payload.IdArea)

    for fila in payload.datos:
        if fila.Tipo not in TIPOS_VALIDOS:
            raise HTTPException(status_code=400, detail=f"Tipo inválido: {fila.Tipo}")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        for tipo in TIPOS_VALIDOS:
            if any(f.Tipo == tipo for f in payload.datos):
                validar_no_supera_presupuesto_tipo(cursor, payload.IdArea, payload.Ano, tipo, payload.datos)

        cursor.execute(
            """
            SELECT Id, Mes, Tipo, IdVertical
            FROM tb_ProyeccionGasto
            WHERE IdArea = ? AND Ano = ? AND Tipo IS NOT NULL
            """,
            (payload.IdArea, payload.Ano)
        )
        registros_actuales = {}
        for row in cursor.fetchall():
            key = (row[1], row[2], row[3])  # (Mes, Tipo, IdVertical)
            registros_actuales[key] = row[0]

        inserted = 0
        updated = 0
        datos_nuevos_keys = set()

        for fila in payload.datos:
            key = (fila.Mes, fila.Tipo, fila.IdVertical)
            datos_nuevos_keys.add(key)

            if key in registros_actuales:
                cursor.execute(
                    """
                    UPDATE tb_ProyeccionGasto
                    SET MontoProyectado = ?, FechaActualizacion = ?
                    WHERE Id = ?
                    """,
                    (fila.MontoProyectado, datetime.now(), registros_actuales[key])
                )
                updated += 1
            else:
                cursor.execute(
                    """
                    INSERT INTO tb_ProyeccionGasto
                        (IdArea, Ano, Mes, IdAgrupacion, IdVertical, Tipo, MontoProyectado, FechaActualizacion)
                    VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        payload.IdArea,
                        payload.Ano,
                        fila.Mes,
                        fila.IdVertical,
                        fila.Tipo,
                        fila.MontoProyectado,
                        datetime.now()
                    )
                )
                inserted += 1

        deleted = 0
        for key, id_registro in registros_actuales.items():
            if key not in datos_nuevos_keys:
                cursor.execute("DELETE FROM tb_ProyeccionGasto WHERE Id = ?", (id_registro,))
                deleted += 1

        conn.commit()
        conn.close()

        return {
            "message": "Proyección OPEX/CAPEX guardada exitosamente",
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted
        }

    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error al guardar proyección OPEX/CAPEX: {str(e)}")


# ============================================================
# 🗑️ DELETE - ELIMINAR UNA PROYECCIÓN ESPECÍFICA
# ============================================================
# SIN CAMBIOS. Sirve para cualquier fila, sea de Agrupación o de Tipo.

@router.delete("/proyeccion/{id_proyeccion}")
def delete_proyeccion(
    id_proyeccion: int,
    user: dict = Depends(verify_token)
):
    """Elimina una fila específica de proyección."""
    validar_rol(user, 2)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT IdArea FROM tb_ProyeccionGasto WHERE Id = ?", (id_proyeccion,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Proyección no encontrada")

    id_area = row[0]
    validar_permiso_area(user, id_area)

    cursor.execute("DELETE FROM tb_ProyeccionGasto WHERE Id = ?", (id_proyeccion,))
    conn.commit()
    conn.close()

    return {"message": "Proyección eliminada correctamente"}