# FacturasPRY — Sistema de Control Presupuestal

Sistema interno de gestión y validación de facturas para la Bolsa Mercantil de Colombia. Permite controlar el gasto por área, validar facturas contra presupuesto asignado, simular impactos y generar reportes de consumo.

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI (Python) |
| Frontend | Streamlit (Python) |
| Base de datos | Microsoft Access (.accdb) vía pyodbc |
| Autenticación | JWT (python-jose) + bcrypt (passlib) |

---

## Estructura del proyecto

```
FacturasPRY/
├── backend/
│   ├── main.py                  # Entrada FastAPI, registro de routers
│   ├── config.py                # Variables de entorno
│   ├── .env                     # Secrets (NO commitear)
│   ├── auth/
│   │   ├── jwt.py               # Generación y verificación de tokens JWT
│   │   ├── password.py          # Hash y verificación bcrypt
│   │   └── permisos.py          # Validación de rol y área
│   ├── db/
│   │   └── connection.py        # Conexión ODBC a Access
│   ├── routers/
│   │   ├── auth.py              # POST /auth/login
│   │   ├── facturas.py          # CRUD facturas por área
│   │   ├── facturas_validacion.py  # Validación presupuestal + estadística
│   │   ├── presupuesto.py       # Presupuesto general, OPEX/CAPEX, proyección
│   │   ├── simulacion.py        # Simulación de impacto de facturas pendientes
│   │   ├── consumo.py           # Registro de facturas aprobadas en tb_Consumo
│   │   ├── consumo_proveedores.py  # Informe de gasto por proveedor
│   │   ├── dashboard.py         # Resumen ejecutivo por área
│   │   ├── dashboard_presupuesto.py  # Dashboard detallado presupuesto vs consumo
│   │   ├── areas.py             # Gestión de áreas
│   │   ├── agrupaciones.py      # Gestión de agrupaciones de gasto
│   │   ├── verticales.py        # Gestión de verticales
│   │   └── usuarios.py          # Gestión de usuarios
│   └── schemas/
│       ├── usuario.py           # Schema Pydantic de usuario (activo)
│       ├── simulacion.py        # Schema de request de simulación
│       └── admin_facturas.py    # ⚠️ Router sin registrar (ver deuda técnica)
├── frontend/
│   ├── main.py                  # Login y navegación principal
│   ├── api/
│   │   └── client.py            # Todas las llamadas HTTP al backend
│   ├── utils/
│   │   └── auth.py              # Helpers de sesión Streamlit
│   └── pages/
│       ├── gestor_facturas.py         # Edición y clasificación de facturas
│       ├── gestor_validacion.py       # Aprobación/rechazo de facturas
│       ├── gestor_presupuesto.py      # Carga de presupuesto y proyección
│       ├── simulacion.py              # Simulador de impacto presupuestal
│       ├── dashboard_presupuesto_vista.py  # Dashboard presupuesto vs consumo
│       ├── Consumo_Proveedores.py     # Informe por proveedor
│       ├── admin_usuarios.py          # Gestión de usuarios (admin)
│       ├── admin_areas.py             # Gestión de áreas (admin)
│       └── admin.py                   # ⚠️ Página legada (ver deuda técnica)
└── database/
    └── dbFacturas.accdb         # Base de datos Access
```

---

## Tablas de la base de datos

| Tabla | Descripción |
|---|---|
| `tb_Usuario` | Credenciales y roles de usuarios |
| `tb_Roles` | Catálogo de roles (1=Admin, 2=Gestor, ...) |
| `tb_Area` | Áreas del negocio |
| `tb_Agrupacion` | Dimensión de gasto por agrupación |
| `tb_Vertical` | Dimensión de clasificación de facturas |
| `tb_Facturas` | Facturas cargadas desde el ERP |
| `tb_Presupuesto` | Presupuesto General / OPEX / CAPEX / Mensual |
| `tb_ProyeccionGasto` | Matriz Mes × Agrupación / Mes × Tipo |
| `tb_Consumo` | Acumulado de facturas aprobadas y descontadas |
| `tb_Proveedor` | Catálogo de proveedores |

---

## Flujos principales

### Login
```
main.py → client.login() → POST /auth/login
  → tb_Usuario (verifica email + bcrypt)
  → devuelve JWT con: sub (usuario_id), rol, area, exp
  → se guarda en st.session_state["access_token"]
```

### Validación de facturas
```
gestor_validacion.py → GET /facturas-validacion/{id_area}/{ano}
  → tb_Facturas (Estado='Pendiente')
  → tb_ProyeccionGasto (proyectado por Agrupación y por Tipo)
  → tb_Consumo (consumido actual)
  → Calcula: cabe_agrupacion = valor <= disponible_agr
  → Calcula: cabe_tipo      = valor <= disponible_tipo
  → Capa estadística: mediana/MAD del historial, burn-rate anual
  → Veredicto determinístico separado del contexto estadístico
```

### Consumo de facturas aprobadas
```
gestor_validacion.py → POST /consumir-facturas/{id_area}/{ano}
  → Transacción única: actualiza tb_Consumo (agrupación + tipo + proveedor)
    y marca tb_Facturas.Descontado = 1
  → Verifica rowcount=1 por factura para detectar race conditions
  → Rollback total si cualquier paso falla
```

### Simulación presupuestal
```
simulacion.py → POST /simulacion/calcular
  → tb_Presupuesto General → techo duro anual (bloquea si se supera)
  → tb_Presupuesto Mensual → alerta operativa (verde/amarillo/rojo)
  → tb_Facturas Aprobadas  → gasto ya ejecutado
  → Nota: usa ValorCOP_M1 (valor sin ajustar); el consumo real usa ValorCOP_M2
```

---

## Instalación y ejecución

> ⚠️ **Este proyecto requiere Windows.** El driver ODBC de Microsoft Access no está disponible en Linux ni macOS.

### Requisitos del sistema
- Windows 10/11
- Python 3.9+
- [Microsoft Access Database Engine 2016 Redistributable](https://www.microsoft.com/en-us/download/details.aspx?id=54920) (64-bit)

### Variables de entorno

Crear `backend/.env` con:

```env
JWT_SECRET_KEY=<clave-segura-minimo-32-caracteres>
DB_PATH=<ruta-absoluta-al-archivo-dbFacturas.accdb>
```

> ⚠️ Nunca commitear el archivo `.env`. Agregar `*.env` al `.gitignore`.

### Instalación de dependencias

```bash
# Instalar dependencias del backend
pip install fastapi uvicorn python-jose passlib[bcrypt] pyodbc python-dotenv

# Instalar dependencias del frontend
pip install streamlit requests plotly pandas
```

> ⚠️ No existe `requirements.txt` todavía. Ver sección de deuda técnica.

### Arrancar el backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### Arrancar el frontend

```bash
cd frontend
streamlit run main.py
```

El frontend espera el backend en `http://localhost:8000` (configurable en `api/client.py`).

---

## Autenticación y permisos

- Los tokens JWT tienen vigencia de **24 horas**
- El token lleva embebidos: `usuario_id`, `rol`, `area`
- El backend **no re-consulta la BD en cada request** — confía en el token
- Implicación: si se desactiva un usuario o cambia su área, el token activo sigue siendo válido hasta expirar
- Los emails de usuario deben terminar en `@bolsamercantil.com.co`
- `validar_permiso_area` lee el área de la factura desde la BD — no confía en el parámetro del cliente

---

## Qué está bien implementado

### Lógica de validación presupuestal (`facturas_validacion.py`)
El módulo más sofisticado del proyecto. Valida cada factura en **dos dimensiones simultáneas** (Agrupación + CAPEX/OPEX), calcula contexto estadístico con mediana/MAD (más robusto que desviación estándar con muestras pequeñas), y mide burn-rate anual. El veredicto determinístico (cabe/no cabe) está explícitamente separado del contexto estadístico (informativo).

### Transacción atómica en consumo (`consumo.py`)
Actualiza tres tablas en una sola transacción con rollback completo en caso de error. Verifica `rowcount=1` por factura para detectar actualizaciones concurrentes.

### JWT falla al arrancar, no en runtime (`auth/jwt.py`)
```python
SECRET_KEY = os.environ["JWT_SECRET_KEY"]  # KeyError al importar si no existe
```
Si falta la variable de entorno, el proceso muere al arrancar con causa obvia.

### Caché por-request en validación
El historial estadístico por bucket (agrupación + mes) se calcula una vez por request, no una vez por factura. El caché vive en el scope del request — sin riesgo de datos obsoletos entre peticiones.

### Permisos verificados desde la BD
```python
rows = execute_query("SELECT IdArea FROM tb_Facturas WHERE Id = ?", (id_factura,))
validar_permiso_area(user, rows[0]["IdArea"])  # el área viene de la BD
```

---

## Deuda técnica conocida

### 🔴 Bugs que rompen funcionalidad ahora mismo

**1. `areas.py` — crear y editar áreas falla con error 500**

`cursor.execute()` recibe los parámetros como argumentos sueltos en lugar de tupla. pyodbc los rechaza.

```python
# INCORRECTO (actual)
cursor.execute("INSERT INTO tb_Area ... VALUES (?, ?, -1)", area.Nombre, area.Descripcion)

# CORRECTO
cursor.execute("INSERT INTO tb_Area ... VALUES (?, ?, -1)", (area.Nombre, area.Descripcion))
```

**2. `admin.py` (frontend) — página inutilizable**

Usa `st.session_state["user"]` que nunca existe (el login guarda `"rol"`, no `"user"`). La página redirige siempre a login. Además llama a `/users` (no existe) sin token Bearer.

**3. `simulacion.py` (frontend) — columna de fecha siempre muestra "-"**

El frontend pide `factura.get('FechaRecepcion')` pero el backend devuelve `FechaFacturacion`. Dato silenciosamente incorrecto.

---

### 🟡 Deuda que romperá con el primer refactor

**4. `agrupaciones.py` y `verticales.py` — tipo incorrecto en `Depends`**

```python
# INCORRECTO — verify_token devuelve dict, no int
usuario_id: int = Depends(verify_token)

# CORRECTO (como está en facturas.py, dashboard.py, consumo.py)
user: dict = Depends(verify_token)
```
Funciona por accidente hoy. Un refactor de `verify_token` lo rompe silenciosamente.

**5. `schemas/admin_facturas.py` — router en carpeta equivocada, sin autenticación, con import roto**
- Es un router FastAPI completo ubicado en `schemas/`
- No tiene `Depends(verify_token)` en ningún endpoint
- Importa `from schemas.factura import FacturaUpdate` que no existe
- No está registrado en `main.py` — el frontend lo llama y recibe 404

**6. Dos patrones de acceso a BD mezclados**
- Módulos viejos: `execute_query()` → una conexión ODBC nueva por query
- Módulos nuevos: `get_connection()` manual → una conexión por request

Los routers que hacen múltiples queries (simulación: 8-15 queries por request) deberían usar el patrón manual.

**7. `main.py` (frontend) — `st.switch_page` con y sin extensión `.py` mezclados**

```python
st.switch_page("pages/Dashboard_presupuesto")    # sin .py
st.switch_page("pages/gestor_presupuesto.py")    # con .py
```
Comportamiento inconsistente entre versiones de Streamlit.

---

### 🟢 Archivos zombie / código muerto

| Archivo | Estado |
|---|---|
| `routers/agrupaciones_router.py` | Duplicado de `agrupaciones.py`, no registrado en `main.py` |
| `routers/areas_router.py` | Vacío (solo header de IDE) |
| `schemas/user.py` | Duplicado de `schemas/usuario.py`, nadie lo importa |
| `schemas/presupuesto.py` | Los schemas reales están definidos inline en el router |
| `pages/gestor_clasificacion_ia.py` | Vacío; `client.py` tiene funciones apuntando a `/crew-ai/ejecuciones` que no existe en el backend |

---

### Contratos implícitos entre frontend y backend

| Contrato | Riesgo si cambia |
|---|---|
| JWT lleva `rol` y `area` embebidos | Cambio de área o desactivación de usuario no tiene efecto hasta que expira el token (24h) |
| Simulación usa `ValorCOP_M1`, consumo usa `ValorCOP_M2` | Una factura puede "caber" en simulación y exceder el presupuesto al consumirse si M2 > M1 |
| `facturas_validacion` usa columna `Mes_pendiente`, simulación usa `Mes` | Si los campos difieren, los dos módulos clasifican la misma factura en meses distintos |

---

## Pendientes de infraestructura

- [ ] Crear `requirements.txt` con versiones pinneadas (`pip freeze > requirements.txt`)
- [ ] Crear `.gitignore` con al menos: `*.env`, `__pycache__/`, `*.pyc`, `database/*.accdb`
- [ ] Rotar `JWT_SECRET_KEY` si el `.env` fue committado al repositorio
- [ ] Evaluar migración de Access a SQL Server Express (el `config.py` ya tiene un `DATABASE_URL` para SQL Server, lo que sugiere que la migración estaba planificada)
- [ ] Agregar rate limiting al endpoint `/auth/login` (sin protección anti-brute force)
- [ ] Unificar mensaje de error del login a "Credenciales inválidas" (actualmente diferencia "Usuario no encontrado" de "Contraseña incorrecta", permitiendo enumerar usuarios)

---

## Limitaciones conocidas de la base de datos (Access)

- Sin concurrencia real — bloqueos a nivel de archivo; con 2+ escrituras simultáneas hay riesgo de error o corrupción
- Sin replicación ni alta disponibilidad
- Límite de 2 GB por archivo `.accdb`
- Solo funciona en Windows (driver ODBC exclusivo de Windows)
- La ruta al archivo está en una variable de entorno — cambiar de equipo requiere actualizar `DB_PATH`

La alternativa de menor esfuerzo es **SQL Server Express**: `config.py` ya tiene el patrón de `DATABASE_URL` para SQL Server y el código usa SQL estándar en su mayoría (excepto `IIF(...)` y booleanos `-1/0` que son específicos de Access).
