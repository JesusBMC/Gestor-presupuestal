"""Consulta y cálculos completos de la vista de proveedores.

Archivo autónomo respecto de _proveedores. Todas sus rutas son GET.
El registro de gasto sigue exclusivamente en consumo.py.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

INDICES = {
    "UX_Consumo_Agrupacion": ("IdArea", "Ano", "Mes", "IdAgrupacion"),
    "UX_Consumo_Tipo": ("IdArea", "Ano", "Mes", "Tipo"),
    "UX_Consumo_Proveedor": ("IdArea", "Ano", "Mes", "IdProvedor"),
}


class ErrorConfiguracion(ValueError):
    pass


class ConflictoConsumo(Exception):
    pass


def columnas(cursor, tabla):
    # tabla es una constante interna, nunca una entrada HTTP.
    cursor.execute(f"SELECT * FROM [{tabla}] WHERE 1 = 0")
    return [c[0] for c in cursor.description]


def validar_esquema(cursor, escritura=False):
    disponibles = columnas(cursor, "tb_Consumo")
    necesarios = ("Id", "IdArea", "Ano", "Mes", "IdAgrupacion", "IdVertical", "Tipo",
                  "IdProvedor", "Monto", "FechaActualizacion", "MontoCAPEX", "MontoOPEX")
    faltan = [c for c in necesarios if c.casefold() not in {x.casefold() for x in disponibles}]
    if faltan:
        raise ErrorConfiguracion("Faltan campos en tb_Consumo: " + ", ".join(faltan) +
                                 ". Ejecuta python -m mantenimiento_consumo preparar.")
    if escritura:
        indices = defaultdict(list)
        # SQLStatistics: NON_UNIQUE=3, INDEX_NAME=5, ORDINAL_POSITION=7, COLUMN_NAME=8.
        for row in cursor.statistics(table="tb_Consumo", unique=True):
            if row[5] is not None and row[8] is not None and not row[3]:
                indices[str(row[5])].append((int(row[7]), str(row[8]).casefold()))
        disponibles_indice = {tuple(c for _, c in sorted(cols)) for cols in indices.values()}
        if any(tuple(c.casefold() for c in campos) not in disponibles_indice for campos in INDICES.values()):
            raise ErrorConfiguracion("Faltan índices únicos de consumo. Ejecuta python -m mantenimiento_consumo preparar.")
    return disponibles


def numero(valor, contexto):
    if valor is None:
        return Decimal("0")
    try:
        n = Decimal(str(valor))
        if not n.is_finite():
            raise InvalidOperation
        return n
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{contexto}: importe nulo o no numérico.") from exc


def _mes_o_none(valor):
    try:
        mes = int(valor)
        return mes if Decimal(str(valor)) == mes and 1 <= mes <= 12 else None
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def leer_saldos(cursor, id_area, ano):
    """Solo resúmenes y catálogo. Esta función NO consulta tb_Facturas."""
    validar_esquema(cursor)
    cursor.execute("""
        SELECT c.[Id], c.[Mes], c.[Monto], c.[MontoCAPEX], c.[MontoOPEX],
               c.[IdProvedor], p.[Nombre], p.[Servicio], p.[Descripcion]
        FROM [tb_Consumo] AS c
        LEFT JOIN [tb_Proveedor] AS p ON c.[IdProvedor] = p.[Id]
        WHERE c.[IdArea] = ? AND c.[Ano] = ?
          AND c.[IdProvedor] > 0
          AND (c.[IdAgrupacion] IS NULL OR c.[IdAgrupacion] = 0)
          AND (c.[Tipo] IS NULL OR c.[Tipo] = '')
        ORDER BY c.[Mes], c.[IdProvedor]
    """, (id_area, ano))
    saldos = []
    for row in cursor.fetchall():
        saldos.append({"Id": row[0], "Mes": row[1], "Monto": numero(row[2], "Monto"),
                       "CAPEX": numero(row[3], "MontoCAPEX"), "OPEX": numero(row[4], "MontoOPEX"),
                       "IdProvedor": row[5], "Proveedor": row[6] or f"Proveedor {row[5]}",
                       "Servicio": row[7] or "", "Descripcion": row[8] or "",
                       "CamposNulos": [nombre for nombre, valor in zip(("Monto", "MontoCAPEX", "MontoOPEX"), row[2:5]) if valor is None]})
    cursor.execute("""
        SELECT [Mes], SUM([Monto]) FROM [tb_Consumo]
        WHERE [IdArea] = ? AND [Ano] = ? AND ([IdProvedor] IS NULL OR [IdProvedor] = 0)
          AND ([IdAgrupacion] IS NOT NULL AND [IdAgrupacion] <> 0) AND ([Tipo] IS NULL OR [Tipo] = '')
        GROUP BY [Mes]
    """, (id_area, ano))
    agrupaciones = {_mes_o_none(r[0]): numero(r[1], "Consumo agrupación") for r in cursor.fetchall()}
    cursor.execute("""
        SELECT [Mes], [Tipo], SUM([Monto]) FROM [tb_Consumo]
        WHERE [IdArea] = ? AND [Ano] = ? AND ([IdProvedor] IS NULL OR [IdProvedor] = 0)
          AND ([IdAgrupacion] IS NULL OR [IdAgrupacion] = 0) AND [Tipo] IN ('CAPEX', 'OPEX')
        GROUP BY [Mes], [Tipo]
    """, (id_area, ano))
    tipos = {(_mes_o_none(r[0]), str(r[1]).upper()): numero(r[2], "Consumo tipo") for r in cursor.fetchall()}
    return saldos, agrupaciones, tipos


from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TIPOS = ("CAPEX", "OPEX", "SIN CLASIFICAR")
ZERO = Decimal("0")


def dinero(valor):
    return None if valor is None else float(valor.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _monto(valor, factura):
    try:
        resultado = Decimal(str(valor))
        if not resultado.is_finite():
            raise InvalidOperation
        return resultado
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Factura {factura}: ValorCOP_M2 vacío o no numérico. Corrige el dato antes de calcular.") from exc


def periodo(ano, mes_corte, hoy):
    if not 2020 <= ano <= 2100:
        raise ValueError("El año debe estar entre 2020 y 2100.")
    if ano > hoy.year:
        raise ValueError("El consumo real solo se consulta para el año actual o anteriores.")
    limite = hoy.month if ano == hoy.year else 12
    corte = limite if mes_corte is None else mes_corte
    if not 1 <= corte <= limite:
        raise ValueError(f"El mes de corte debe estar entre 1 y {limite} para ese año.")
    # El último día también se considera abierto hasta que termine el día.
    parcial = ano == hoy.year and corte == hoy.month
    fecha = hoy if parcial else date(ano, corte, monthrange(ano, corte)[1])
    return {"ano": ano, "mes_corte": corte, "fecha_corte": fecha.isoformat(),
            "mes_parcial": parcial, "meses_completos": corte - int(parcial),
            "ano_actual": hoy.year, "mes_actual": hoy.month}


def construir_informe(facturas, id_area, ano, mes_corte=None, tipo=None, hoy=None):
    """facturas contiene solo registros Aprobado + Descontado, de un área/año."""
    hoy = hoy or date.today()
    p = periodo(ano, mes_corte, hoy)
    if tipo is not None and tipo not in TIPOS:
        raise ValueError("Tipo debe ser CAPEX, OPEX o SIN CLASIFICAR.")
    corte, cerrados = p["mes_corte"], p["meses_completos"]
    proveedores, detalle, ids = {}, [], set()
    futuros, monto_futuro, desconocidos = 0, ZERO, 0
    for fac in facturas:
        fid = fac["Id"]
        if fid in ids:
            raise ValueError(f"Factura Id {fid} repetida en la lectura. No se sumó el informe.")
        ids.add(fid)
        raw_mes = fac["Mes"]
        try:
            mes = int(raw_mes)
            if Decimal(str(raw_mes)) != mes or not 1 <= mes <= 12:
                raise ValueError
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ValueError(f"Factura {fid}: Mes inválido ({raw_mes!r}).") from exc
        valor = _monto(fac["ValorCOP_M2"], fid)
        tipo_original = str(fac.get("Tipo") or "").strip().upper()
        tipo_fac = tipo_original if tipo_original in TIPOS[:2] else TIPOS[2]
        if tipo and tipo_fac != tipo:
            continue
        if mes > corte:
            futuros += 1
            monto_futuro += valor
            continue
        if tipo_fac == TIPOS[2]:
            desconocidos += 1
        clave = fac["ClaveProveedor"]
        if clave not in proveedores:
            proveedores[clave] = {"clave": clave, "nombre": fac["Proveedor"],
                                  "meses": {m: {t: ZERO for t in TIPOS} for m in range(1, corte + 1)},
                                  "facturas": 0}
        bucket = proveedores[clave]
        bucket["meses"][mes][tipo_fac] += valor
        bucket["facturas"] += 1
        detalle.append({"Id": fid, "Factura": str(fac.get("NumFactura") or ""),
                        "ClaveProveedor": clave, "Proveedor": fac["Proveedor"], "Mes": mes,
                        "Tipo": tipo_fac, "TipoOriginal": tipo_original, "Consumo": dinero(valor),
                        "Agrupacion": fac.get("Agrupacion", ""), "Descripcion": fac.get("Descripcion", "")})
    filas, mensual = [], []
    totales = {t: ZERO for t in TIPOS}
    total_proyeccion = ZERO
    for clave, proveedor in proveedores.items():
        por_tipo = {t: sum((m[t] for m in proveedor["meses"].values()), ZERO) for t in TIPOS}
        acumulado = sum(por_tipo.values(), ZERO)
        actual = sum(proveedor["meses"][corte].values(), ZERO)
        historico = sum((sum(proveedor["meses"][m].values(), ZERO) for m in range(1, cerrados + 1)), ZERO)
        promedio = historico / cerrados if cerrados else None
        # Enero parcial: no inventar un patrón sin meses completos.
        if corte == 12 and not p["mes_parcial"]:
            proyeccion = acumulado
        elif promedio is None:
            proyeccion = None
        else:
            # Importes negativos se muestran; el gasto futuro extrapolado tiene piso 0.
            base = max(promedio, ZERO)
            ajuste_mes = max(base - actual, ZERO) if p["mes_parcial"] else ZERO
            proyeccion = acumulado + ajuste_mes + base * (12 - corte)
        if proyeccion is not None:
            total_proyeccion += proyeccion
        fila = {"ClaveProveedor": clave, "Proveedor": proveedor["nombre"],
                "CAPEX": dinero(por_tipo["CAPEX"]), "OPEX": dinero(por_tipo["OPEX"]),
                "SinClasificar": dinero(por_tipo[TIPOS[2]]), "Acumulado": dinero(acumulado),
                "ConsumoMesCorte": dinero(actual), "PromedioMensualAlCorte": dinero(acumulado / corte),
                "PromedioMesesCompletos": dinero(promedio), "EstimacionAnual": dinero(proyeccion),
                "PorConsumirEstimado": dinero(proyeccion - acumulado) if proyeccion is not None else None,
                "Facturas": proveedor["facturas"],
                "MesesConConsumo": sum(any(v != 0 for v in mes.values()) for mes in proveedor["meses"].values())}
        filas.append(fila)
        for t in TIPOS:
            totales[t] += por_tipo[t]
        for mes, valores in proveedor["meses"].items():
            mensual.append({"ClaveProveedor": clave, "Proveedor": proveedor["nombre"], "Mes": mes,
                            "CAPEX": dinero(valores["CAPEX"]), "OPEX": dinero(valores["OPEX"]),
                            "SinClasificar": dinero(valores[TIPOS[2]]), "Total": dinero(sum(valores.values(), ZERO))})
    total = sum(totales.values(), ZERO)
    pastel_valido = total > 0 and all(f["Acumulado"] >= 0 for f in filas)
    for fila in filas:
        fila["ParticipacionPct"] = round(fila["Acumulado"] / float(total) * 100, 4) if pastel_valido else None
    filas.sort(key=lambda f: (-f["Acumulado"], f["Proveedor"].casefold()))
    serie = []
    acumulado_serie = ZERO
    for mes in range(1, corte + 1):
        valores = {t: sum((prov["meses"][mes][t] for prov in proveedores.values()), ZERO) for t in TIPOS}
        suma = sum(valores.values(), ZERO)
        acumulado_serie += suma
        serie.append({"Mes": mes, "CAPEX": dinero(valores["CAPEX"]), "OPEX": dinero(valores["OPEX"]),
                      "SinClasificar": dinero(valores[TIPOS[2]]), "Total": dinero(suma), "Acumulado": dinero(acumulado_serie)})
    advertencias = []
    if futuros:
        advertencias.append(f"Se excluyen {futuros} registros consumidos posteriores al mes de corte. Consulta diciembre para el cierre de un año anterior.")
    if desconocidos:
        advertencias.append(f"{desconocidos} registros del corte no tienen Tipo CAPEX/OPEX válido. Se incluyen como SIN CLASIFICAR.")
    if not cerrados:
        advertencias.append("Aún no hay meses completos del año: la estimación anual no está disponible.")
    elif cerrados < 3:
        advertencias.append("La estimación usa menos de tres meses completos; la base es limitada.")
    if any(f["Consumo"] < 0 for f in detalle):
        advertencias.append("Hay importes negativos: los totales son netos. La tasa de gasto futuro tiene mínimo cero; revisa ajustes y notas crédito.")
    return {"id_area": id_area, "periodo": p, "filtro_tipo": tipo or "TODOS",
            "resumen": {"Acumulado": dinero(total), "CAPEX": dinero(totales["CAPEX"]),
                        "OPEX": dinero(totales["OPEX"]), "SinClasificar": dinero(totales[TIPOS[2]]),
                        "ConsumoMesCorte": serie[-1]["Total"], "Facturas": len(detalle),
                        "Proveedores": sum(f["ClaveProveedor"] != "sin_proveedor" for f in filas),
                        "PromedioMensualAlCorte": dinero(total / corte),
                        "EstimacionAnual": dinero(total_proyeccion) if cerrados else None,
                        "MesesBase": cerrados, "RegistrosFueraCorte": futuros,
                        "MontoFueraCorte": dinero(monto_futuro), "PastelValido": pastel_valido},
            "proveedores": filas, "mensual": mensual, "serie": serie,
            "facturas": detalle, "advertencias": advertencias}


from collections import defaultdict
from decimal import Decimal


def _tolerancia(*montos):
    """Margen de representación DOUBLE, limitado a medio centavo de COP."""
    escala = max((abs(m) for m in montos), default=Decimal("0"))
    return min(Decimal("0.005"), max(Decimal("0.0001"), escala * Decimal("1e-14")))


def construir_resumen(saldos, agrupaciones, tipos, id_area, ano, mes_corte, tipo, hoy):
    corte = periodo(ano, mes_corte, hoy)["mes_corte"]
    totales = defaultdict(lambda: Decimal("0"))
    componentes = defaultdict(lambda: Decimal("0"))
    entradas, catalogo, claves = [], {}, set()
    avisos, sin_mes = [], []
    for s in saldos:
        mes = _mes_o_none(s["Mes"])
        if s.get("CamposNulos"):
            avisos.append(f"Consumo {s['Id']}: campos vacíos ({', '.join(s['CamposNulos'])}); se calculan como cero. El importe de Monto no desglosado se muestra en Sin clasificar.")
        if mes is None:
            resto = s["Monto"] - s["CAPEX"] - s["OPEX"]
            importe = s["Monto"] if tipo is None else {"CAPEX": s["CAPEX"], "OPEX": s["OPEX"], "SIN CLASIFICAR": resto}.get(tipo, Decimal("0"))
            sin_mes.append({"Id": s["Id"], "IdProvedor": s["IdProvedor"], "Proveedor": s["Proveedor"],
                            "MesOriginal": s["Mes"], "Monto": dinero(s["Monto"]),
                            "CAPEX": dinero(s["CAPEX"]), "OPEX": dinero(s["OPEX"]),
                            "SinClasificar": dinero(resto), "MontoFiltro": dinero(importe)})
            continue
        if (mes, s["IdProvedor"]) in claves:
            avisos.append(f"Proveedor {s['IdProvedor']}, mes {mes}: hay varias filas; se suman sus importes registrados.")
        claves.add((mes, s["IdProvedor"]))
        totales[mes] += s["Monto"]
        for t in ("CAPEX", "OPEX"):
            componentes[mes, t] += s[t]
        clave = f"id:{s['IdProvedor']}"
        catalogo[clave] = {"Servicio": s["Servicio"], "Descripcion": s["Descripcion"]}
        resto = s["Monto"] - s["CAPEX"] - s["OPEX"]
        if abs(resto) <= _tolerancia(s["Monto"], s["CAPEX"], s["OPEX"]):
            resto = Decimal("0")
        montos = {"CAPEX": s["CAPEX"], "OPEX": s["OPEX"], "SIN CLASIFICAR": resto}
        # El cálculo recibe componentes del saldo guardado, nunca facturas de la BD.
        for t, importe in montos.items():
            if importe != 0 or t == "CAPEX":
                entradas.append({"Id": f"{s['Id']}:{t}", "Mes": mes, "Tipo": t,
                                  "ValorCOP_M2": importe, "ClaveProveedor": clave,
                                  "Proveedor": s["Proveedor"]})
    for mes in range(1, corte + 1):
        agrupado = agrupaciones.get(mes, Decimal("0"))
        if abs(totales[mes] - agrupado) > _tolerancia(totales[mes], agrupado):
            avisos.append(f"Mes {mes}: proveedores ({dinero(totales[mes])}) y agrupaciones ({dinero(agrupado)}) difieren. Se muestra el consumo registrado de proveedores.")
        for t in ("CAPEX", "OPEX"):
            por_tipo = tipos.get((mes, t), Decimal("0"))
            if abs(componentes[mes, t] - por_tipo) > _tolerancia(componentes[mes, t], por_tipo):
                avisos.append(f"Mes {mes}: el desglose {t} de proveedores ({dinero(componentes[mes, t])}) difiere del consumo por tipo ({dinero(por_tipo)}).")
    resultado = construir_informe(entradas, id_area, ano, mes_corte, tipo, hoy)
    resultado.pop("facturas", None)
    resultado["resumen"].pop("Facturas", None)
    # Nunca presentar el número de componentes agregados como cantidad de facturas.
    for p in resultado["proveedores"]:
        p.pop("Facturas", None)
        p.update(catalogo[p["ClaveProveedor"]])
    resultado["advertencias"] = [a.replace("registros consumidos", "componentes de consumo").replace("registros del corte", "componentes del corte") for a in resultado["advertencias"]]
    if sin_mes:
        avisos.append(f"Hay {len(sin_mes)} registro(s) de proveedor sin mes válido. Se muestran aparte y no se incluyen en el acumulado al corte, los promedios ni la estimación; no es posible determinar su mes.")
    if None in agrupaciones or any(m is None for m, t in tipos):
        avisos.append("Hay registros de agrupación o tipo sin mes válido. No se asignan a ningún mes en la comparación.")
    resultado["sin_mes"] = sin_mes
    resultado["resumen"]["MontoSinMes"] = sum(r["MontoFiltro"] for r in sin_mes)
    resultado["advertencias"].extend(dict.fromkeys(avisos))
    resultado["fuente"] = {"tabla": "tb_Consumo", "clave_proveedor": "IdProvedor",
                            "catalogo": "tb_Proveedor", "detalle_facturas_consultado": False}
    return resultado


import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from auth.jwt import verify_token
from auth.permisos import validar_permiso_area
from db.connection import get_connection

router = APIRouter(prefix="/consumo-proveedores", tags=["Consumo por proveedor"])
logger = logging.getLogger(__name__)


def _ahora():
    try:
        return datetime.now(ZoneInfo("America/Bogota"))
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(500, "Falta tzdata: ejecuta python -m pip install tzdata") from exc


@router.get("/{id_area}/esquema")
def get_esquema_proveedores(id_area: int = Path(..., ge=1), user: dict = Depends(verify_token)):
    validar_permiso_area(user, id_area)
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        disponibles = columnas(cursor, "tb_Consumo")
        try:
            validar_esquema(cursor)
            return {"configurado": True, "tabla": "tb_Consumo", "campo": "IdProvedor", "catalogo": "tb_Proveedor"}
        except ErrorConfiguracion as exc:
            return {"configurado": False, "columnas_consumo": disponibles, "detalle": str(exc)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("No se pudo consultar el esquema de proveedores")
        raise HTTPException(500, "No se pudo leer el esquema. Revisa la conexión y el registro del backend.") from exc
    finally:
        if conn is not None:
            conn.close()


@router.get("/{id_area}/{ano}")
def get_consumo_proveedores(
    id_area: int = Path(..., ge=1), ano: int = Path(..., ge=2020, le=2100),
    mes_corte: Optional[int] = Query(None, ge=1, le=12),
    tipo: Optional[str] = Query(None), user: dict = Depends(verify_token),
):
    validar_permiso_area(user, id_area)
    ahora = _ahora()
    conn = None
    try:
        periodo(ano, mes_corte, ahora.date())
        conn = get_connection()
        saldos, agrupaciones, tipos = leer_saldos(conn.cursor(), id_area, ano)
        informe = construir_resumen(saldos, agrupaciones, tipos, id_area, ano, mes_corte, tipo, ahora.date())
        informe["periodo"]["consultado_en"] = ahora.isoformat()
        informe["periodo"]["zona_horaria"] = "America/Bogota"
        return informe
    except ErrorConfiguracion as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error en consumo por proveedor; área=%s año=%s", id_area, ano)
        raise HTTPException(500, "No se pudo consultar el consumo por proveedor. Revisa el registro del backend.") from exc
    finally:
        if conn is not None:
            conn.close()
