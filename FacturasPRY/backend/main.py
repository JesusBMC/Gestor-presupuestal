from dotenv import load_dotenv

load_dotenv()
 
from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware
 
# ============================================================

# IMPORTAR TODOS LOS ROUTERS

# ============================================================

from routers import (

    auth,

    usuarios,

    dashboard,

    facturas,

    presupuesto,

    simulacion,

    areas,

    agrupaciones,

    verticales,
    
    facturas_validacion,
    
    consumo,
    
    dashboard_presupuesto,
    
    consumo_proveedores

)
 
 
# ============================================================

# CREAR APP FASTAPI

# ============================================================

app = FastAPI(

    title="Sistema de Control Presupuestal",

    description="API para gestión de presupuestos y facturas",

    version="1.0.0"

)
 
# ============================================================

# CONFIGURAR CORS (Para que Streamlit pueda conectarse)

# ============================================================

app.add_middleware(

    CORSMiddleware,

    allow_origins=["http://localhost:8501", "http://localhost:3000"],  # Frontend

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)
 
# ============================================================

# REGISTRAR TODOS LOS ROUTERS

# ============================================================

app.include_router(auth.router)

app.include_router(usuarios.router)

app.include_router(dashboard.router)

app.include_router(facturas.router)

app.include_router(presupuesto.router)

app.include_router(simulacion.router)

app.include_router(areas.router)

app.include_router(agrupaciones.router)

app.include_router(verticales.router)

app.include_router(dashboard_presupuesto.router)

app.include_router(consumo_proveedores.router) 


app.include_router(facturas_validacion.router) 

app.include_router(consumo.router)
 
# ============================================================

# ENDPOINT DE SALUD (HEALTH CHECK)

# ============================================================

@app.get("/")

def root():

    """Verificar que API está funcionando"""

    return {

        "message": "API de Control Presupuestal funcionando",

        "version": "1.0.0",

        "endpoints": {

            "auth": "/auth/login (POST)",

            "users": "/users/ (GET, POST, PUT, DELETE)",

            "dashboard": "/dashboard/{id_area} (GET)",

            "facturas": "/facturas/pendientes/{id_area} (GET)",

            "presupuesto": "/presupuesto/{id_area} (GET, POST, PUT)",

            "simulacion": "/simulacion/calcular (POST)",

            "areas": "/areas/ (GET)",

            "agrupaciones": "/agrupaciones/{id_area} (GET, POST, PUT, DELETE)",

            "verticales": "/verticales/{id_area} (GET, POST, PUT, DELETE)"

        }

    }



 
# ============================================================

# PARA EJECUTAR:

# uvicorn main:app --reload --host 0.0.0.0 --port 8000

# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
 