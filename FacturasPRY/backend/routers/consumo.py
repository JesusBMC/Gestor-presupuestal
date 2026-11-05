from fastapi import APIRouter, Depends, HTTPException

from decimal import Decimal

from db.connection import get_connection

from auth.jwt import verify_token

from auth.permisos import validar_permiso_area

from datetime import datetime


router = APIRouter(
    prefix="/consumir-facturas",
    tags=["Consumo"]
)


# ============================================================
# UTILIDADES
# ============================================================

def _to_float(value):
    """Convierte Decimal a float. None -> 0.0"""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# Toda la escritura de consumo está en este archivo.
# Agrupación, tipo y proveedor son desgloses del mismo gasto.
# registrar_lote no abre conexiones ni hace commit: utiliza la transacción
# del botón o de la reconstrucción manual, sin duplicar procesamiento.

def registrar_lote(cursor, id_area, ano):
    """Lógica original de consumo, extendida con el acumulado por proveedor."""

    # ========================================================
    # PASO 1: BUSCAR FACTURAS APROBADAS NO DESCONTADAS
    # ========================================================

    cursor.execute("""
        SELECT
            Id,
            NumFactura,
            ValorCOP_M2,
            Mes,
            IdAgrupacion,
            Tipo,
            IdProveedor
        FROM tb_Facturas
        WHERE IdArea = ?
          AND Ano = ?
          AND Estado = 'Aprobado'
          AND Descontado = 0
        ORDER BY
            Mes ASC,
            IdAgrupacion ASC,
            Tipo ASC
    """, (id_area, ano))

    facturas_raw = []

    for row in cursor.fetchall():
        facturas_raw.append({
            "Id": row[0],
            "NumFactura": row[1],
            "ValorCOP_M2": _to_float(row[2]),
            "Mes": row[3],
            "IdAgrupacion": row[4],
            "Tipo": row[5],  # NULL, 'CAPEX', 'OPEX'
            "IdProveedor": row[6]
        })

    # ========================================================
    # NO HAY FACTURAS PARA CONSUMIR
    # ========================================================

    if not facturas_raw:
        return {
            "message": "No hay facturas aprobadas para consumir",
            "resumen": {
                "total_facturas": 0,
                "monto_total": 0.0,
                "grupos_creados": 0,
                "grupos_actualizados": 0,
                "por_tipo": {
                    "agrupacion": {"facturas": 0, "monto": 0.0},
                    "capex": {"facturas": 0, "monto": 0.0},
                    "opex": {"facturas": 0, "monto": 0.0},
                    "proveedor": {"facturas": 0, "monto": 0.0}
                }
            },
            "detalle": []
        }

    # ========================================================
    # PASO 2: AGRUPAR PARA EL MUNDO AGRUPACIÓN
    #
    # TODAS las facturas participan aquí, sin importar Tipo.
    # ========================================================

    grupos_agrupacion = {}

    for fac in facturas_raw:

        key = (fac["Mes"], fac["IdAgrupacion"])

        if key not in grupos_agrupacion:
            grupos_agrupacion[key] = {
                "monto": 0.0,
                "cantidad": 0,
                "facturas": []
            }

        grupos_agrupacion[key]["monto"] += fac["ValorCOP_M2"]
        grupos_agrupacion[key]["cantidad"] += 1
        grupos_agrupacion[key]["facturas"].append(fac["NumFactura"])

    # ========================================================
    # PASO 3: AGRUPAR PARA EL MUNDO TIPO (CAPEX / OPEX)
    #
    # Solo las facturas con Tipo definido participan aquí,
    # ADEMÁS de haber participado en el paso 2.
    # ========================================================

    grupos_capex = {}
    grupos_opex = {}

    for fac in facturas_raw:

        if fac["Tipo"] == 'CAPEX':

            key = (fac["Mes"], 'CAPEX')

            if key not in grupos_capex:
                grupos_capex[key] = {
                    "monto": 0.0,
                    "cantidad": 0,
                    "facturas": []
                }

            grupos_capex[key]["monto"] += fac["ValorCOP_M2"]
            grupos_capex[key]["cantidad"] += 1
            grupos_capex[key]["facturas"].append(fac["NumFactura"])

        elif fac["Tipo"] == 'OPEX':

            key = (fac["Mes"], 'OPEX')

            if key not in grupos_opex:
                grupos_opex[key] = {
                    "monto": 0.0,
                    "cantidad": 0,
                    "facturas": []
                }

            grupos_opex[key]["monto"] += fac["ValorCOP_M2"]
            grupos_opex[key]["cantidad"] += 1
            grupos_opex[key]["facturas"].append(fac["NumFactura"])

    # ========================================================
    # PASO 3B: AGRUPAR TAMBIÉN POR PROVEEDOR
    # Una fila por área/año/mes/proveedor, con CAPEX y OPEX dentro.
    # ========================================================

    grupos_proveedor = {}
    avisos = []
    sin_proveedor = []
    for fac in facturas_raw:
        id_proveedor = fac["IdProveedor"]
        if id_proveedor is None or id_proveedor <= 0:
            sin_proveedor.append(fac)
            avisos.append(f"Factura {fac['NumFactura']}: sin proveedor; se registra en agrupación y tipo, sin crear un proveedor ficticio.")
            continue
        key = (fac["Mes"], id_proveedor)
        if key not in grupos_proveedor:
            grupos_proveedor[key] = {"monto": 0.0, "capex": 0.0, "opex": 0.0}
        grupos_proveedor[key]["monto"] += fac["ValorCOP_M2"]
        if fac["Tipo"] == 'CAPEX':
            grupos_proveedor[key]["capex"] += fac["ValorCOP_M2"]
        elif fac["Tipo"] == 'OPEX':
            grupos_proveedor[key]["opex"] += fac["ValorCOP_M2"]

    # ========================================================
    # PASO 4: INSERTAR/ACTUALIZAR EN tb_Consumo (AGRUPACIÓN)
    # ========================================================

    grupos_creados = 0
    grupos_actualizados = 0

    for (mes, id_agr), datos in grupos_agrupacion.items():

        cursor.execute("""
            SELECT Id
            FROM tb_Consumo
            WHERE IdArea = ?
              AND Ano = ?
              AND (Mes = ? OR (Mes IS NULL AND ? IS NULL))
              AND (IdAgrupacion = ? OR (IdAgrupacion IS NULL AND ? IS NULL))
              AND Tipo IS NULL
              AND IdProvedor IS NULL
        """, (id_area, ano, mes, mes, id_agr, id_agr))

        existe = cursor.fetchone()

        if existe:
            cursor.execute("""
                UPDATE tb_Consumo
                SET
                    Monto = IIF(Monto IS NULL, 0, Monto) + ?,
                    FechaActualizacion = ?
                WHERE Id = ?
            """, (datos["monto"], datetime.now(), existe[0]))
            grupos_actualizados += 1
        else:
            cursor.execute("""
                INSERT INTO tb_Consumo
                (IdArea, Ano, Mes, IdAgrupacion, Tipo, IdProvedor, IdVertical, Monto, FechaActualizacion)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
            """, (id_area, ano, mes, id_agr, datos["monto"], datetime.now()))
            grupos_creados += 1

    # ========================================================
    # PASO 5: INSERTAR/ACTUALIZAR EN tb_Consumo (CAPEX)
    # ========================================================

    for (mes, tipo), datos in grupos_capex.items():

        cursor.execute("""
            SELECT Id
            FROM tb_Consumo
            WHERE IdArea = ?
              AND Ano = ?
              AND (Mes = ? OR (Mes IS NULL AND ? IS NULL))
              AND Tipo = 'CAPEX'
              AND IdAgrupacion IS NULL
              AND IdProvedor IS NULL
        """, (id_area, ano, mes, mes))

        existe = cursor.fetchone()

        if existe:
            cursor.execute("""
                UPDATE tb_Consumo
                SET
                    Monto = IIF(Monto IS NULL, 0, Monto) + ?,
                    FechaActualizacion = ?
                WHERE Id = ?
            """, (datos["monto"], datetime.now(), existe[0]))
            grupos_actualizados += 1
        else:
            cursor.execute("""
                INSERT INTO tb_Consumo
                (IdArea, Ano, Mes, IdAgrupacion, Tipo, IdProvedor, IdVertical, Monto, FechaActualizacion)
                VALUES (?, ?, ?, NULL, 'CAPEX', NULL, NULL, ?, ?)
            """, (id_area, ano, mes, datos["monto"], datetime.now()))
            grupos_creados += 1

    # ========================================================
    # PASO 6: INSERTAR/ACTUALIZAR EN tb_Consumo (OPEX)
    # ========================================================

    for (mes, tipo), datos in grupos_opex.items():

        cursor.execute("""
            SELECT Id
            FROM tb_Consumo
            WHERE IdArea = ?
              AND Ano = ?
              AND (Mes = ? OR (Mes IS NULL AND ? IS NULL))
              AND Tipo = 'OPEX'
              AND IdAgrupacion IS NULL
              AND IdProvedor IS NULL
        """, (id_area, ano, mes, mes))

        existe = cursor.fetchone()

        if existe:
            cursor.execute("""
                UPDATE tb_Consumo
                SET
                    Monto = IIF(Monto IS NULL, 0, Monto) + ?,
                    FechaActualizacion = ?
                WHERE Id = ?
            """, (datos["monto"], datetime.now(), existe[0]))
            grupos_actualizados += 1
        else:
            cursor.execute("""
                INSERT INTO tb_Consumo
                (IdArea, Ano, Mes, IdAgrupacion, Tipo, IdProvedor, IdVertical, Monto, FechaActualizacion)
                VALUES (?, ?, ?, NULL, 'OPEX', NULL, NULL, ?, ?)
            """, (id_area, ano, mes, datos["monto"], datetime.now()))
            grupos_creados += 1

    # ========================================================
    # PASO 6B: INSERTAR/ACTUALIZAR PROVEEDORES
    # Mismo cursor y transacción que agrupación y CAPEX/OPEX.
    # ========================================================

    for (mes, id_proveedor), datos in grupos_proveedor.items():
        cursor.execute("""
            SELECT Id, MontoCAPEX, MontoOPEX
            FROM tb_Consumo
            WHERE IdArea = ? AND Ano = ? AND (Mes = ? OR (Mes IS NULL AND ? IS NULL))
              AND IdProvedor = ?
              AND IdAgrupacion IS NULL AND Tipo IS NULL
        """, (id_area, ano, mes, mes, id_proveedor))
        existe = cursor.fetchone()
        if existe:
            if existe[1] is None or existe[2] is None:
                avisos.append(f"Consumo {existe[0]}: desglose anterior incompleto; los campos vacíos parten de cero. El importe previo no identificado permanece sin clasificar.")
            cursor.execute("""
                UPDATE tb_Consumo
                SET Monto = IIF(Monto IS NULL, 0, Monto) + ?,
                    MontoCAPEX = IIF(MontoCAPEX IS NULL, 0, MontoCAPEX) + ?,
                    MontoOPEX = IIF(MontoOPEX IS NULL, 0, MontoOPEX) + ?,
                    FechaActualizacion = ?
                WHERE Id = ?
            """, (datos["monto"], datos["capex"], datos["opex"], datetime.now(), existe[0]))
            grupos_actualizados += 1
        else:
            cursor.execute("""
                INSERT INTO tb_Consumo
                (IdArea, Ano, Mes, IdAgrupacion, Tipo, IdProvedor, IdVertical,
                 Monto, MontoCAPEX, MontoOPEX, FechaActualizacion)
                VALUES (?, ?, ?, NULL, NULL, ?, NULL, ?, ?, ?, ?)
            """, (id_area, ano, mes, id_proveedor, datos["monto"],
                  datos["capex"], datos["opex"], datetime.now()))
            grupos_creados += 1

    # ========================================================
    # PASO 7: MARCAR FACTURAS COMO DESCONTADAS
    #
    # Cada factura se marca UNA sola vez, sin importar en
    # cuántos desgloses haya actualizado.
    # ========================================================

    for fac in facturas_raw:
        if fac["Mes"] is None:
            avisos.append(f"Factura {fac['NumFactura']}: se conserva el mes vacío; su consumo no se puede ubicar en la serie mensual.")
    ids_unicos = set(f["Id"] for f in facturas_raw)

    for id_fac in ids_unicos:
        cursor.execute("""
            UPDATE tb_Facturas
            SET Descontado = 1
            WHERE Id = ? AND IdArea = ? AND Ano = ?
              AND Estado = 'Aprobado' AND Descontado = 0
        """, (id_fac, id_area, ano))
        if cursor.rowcount != 1:
            raise ValueError("Una factura cambió durante el consumo. Se revierte el lote; vuelve a consultar.")


    # ========================================================
    # PASO 8: DETALLE POR AGRUPACIÓN Y POR TIPO
    #
    # El detalle de agrupación recorre TODAS las facturas
    # (facturas_raw), no un subconjunto filtrado por Tipo,
    # porque toda factura participa en su agrupación sin
    # importar si además es CAPEX u OPEX.
    # ========================================================

    detalle = []

    # AGRUPACIÓN
    ids_agrupacion_presentes = set(f["IdAgrupacion"] for f in facturas_raw)

    for id_agr in ids_agrupacion_presentes:

        cursor.execute("""
            SELECT Nombre
            FROM tb_Agrupacion
            WHERE Id = ?
        """, (id_agr,))
        row_agr = cursor.fetchone()
        nombre_agr = row_agr[0] if row_agr else f"Agrupación {id_agr}"

        cursor.execute("""
            SELECT
                COUNT(*),
                SUM(ValorCOP_M2)
            FROM tb_Facturas
            WHERE IdArea = ?
              AND Ano = ?
              AND IdAgrupacion = ?
              AND Descontado <> 0
        """, (id_area, ano, id_agr))

        row_data = cursor.fetchone()
        cantidad = row_data[0] if row_data else 0
        monto = _to_float(row_data[1]) if row_data else 0.0

        detalle.append({
            "Tipo": "Agrupación",
            "Nombre": nombre_agr,
            "cantidad_facturas": cantidad,
            "monto": monto
        })

    # CAPEX
    cursor.execute("""
        SELECT
            COUNT(*),
            SUM(ValorCOP_M2)
        FROM tb_Facturas
        WHERE IdArea = ?
          AND Ano = ?
          AND Descontado <> 0
          AND Tipo = 'CAPEX'
    """, (id_area, ano))

    row_data = cursor.fetchone()
    cantidad_capex = row_data[0] if row_data else 0
    monto_capex = _to_float(row_data[1]) if row_data else 0.0

    if cantidad_capex > 0:
        detalle.append({
            "Tipo": "CAPEX",
            "Nombre": "CAPEX",
            "cantidad_facturas": cantidad_capex,
            "monto": monto_capex
        })

    # OPEX
    cursor.execute("""
        SELECT
            COUNT(*),
            SUM(ValorCOP_M2)
        FROM tb_Facturas
        WHERE IdArea = ?
          AND Ano = ?
          AND Descontado <> 0
          AND Tipo = 'OPEX'
    """, (id_area, ano))

    row_data = cursor.fetchone()
    cantidad_opex = row_data[0] if row_data else 0
    monto_opex = _to_float(row_data[1]) if row_data else 0.0

    if cantidad_opex > 0:
        detalle.append({
            "Tipo": "OPEX",
            "Nombre": "OPEX",
            "cantidad_facturas": cantidad_opex,
            "monto": monto_opex
        })


    # ========================================================
    # RESPUESTA
    # ========================================================

    total_facturas = len(facturas_raw)
    monto_total = sum(f["ValorCOP_M2"] for f in facturas_raw)

    facturas_capex_lista = [f for f in facturas_raw if f["Tipo"] == 'CAPEX']
    facturas_opex_lista = [f for f in facturas_raw if f["Tipo"] == 'OPEX']

    return {
        "message": "Facturas consumidas correctamente",
        "advertencias": list(dict.fromkeys(avisos)),
        "sin_proveedor": {"facturas": len(sin_proveedor), "monto": sum(f["ValorCOP_M2"] for f in sin_proveedor)},
        "resumen": {
            "total_facturas": total_facturas,
            "monto_total": monto_total,
            "grupos_creados": grupos_creados,
            "grupos_actualizados": grupos_actualizados,
            "por_tipo": {
                "agrupacion": {
                    "facturas": total_facturas,
                    "monto": monto_total
                },
                "capex": {
                    "facturas": len(facturas_capex_lista),
                    "monto": sum(f["ValorCOP_M2"] for f in facturas_capex_lista)
                },
                "opex": {
                    "facturas": len(facturas_opex_lista),
                    "monto": sum(f["ValorCOP_M2"] for f in facturas_opex_lista)
                },
                "proveedor": {
                    "facturas": total_facturas - len(sin_proveedor),
                    "monto": monto_total - sum(f["ValorCOP_M2"] for f in sin_proveedor)
                }
            }
        },
        "detalle": detalle
    }



@router.post("/{id_area}/{ano}")
def consumir_facturas(id_area: int, ano: int, user: dict = Depends(verify_token)):
    validar_permiso_area(user, id_area)
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        respuesta = registrar_lote(conn.cursor(), id_area, ano)
        # Confirmar agrupación, tipo, proveedor y marcas una sola vez.
        conn.commit()
        return respuesta
    except Exception as e:
        if conn is not None:
            conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error consumiendo facturas: {str(e)}"
        ) from e
    finally:
        if conn is not None:
            conn.close()
