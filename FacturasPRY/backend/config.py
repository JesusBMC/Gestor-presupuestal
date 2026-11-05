import os
from dotenv import load_dotenv

load_dotenv()

# BASE DE DATOS
DATABASE_URL = os.getenv("DATABASE_URL", "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=PresupuestosBMC;Trusted_Connection=yes;")

# SEGURIDAD
SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-en-produccion-con-clave-larga-segura")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# DEBUG
DEBUG = os.getenv("DEBUG", "False") == "True"

# FRONTEND
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")