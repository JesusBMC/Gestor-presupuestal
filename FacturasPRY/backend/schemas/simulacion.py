from pydantic import BaseModel

class SimulacionRequest(BaseModel):
    """Schema para calcular simulación de presupuesto"""
    facturaIds: list
    IdArea: int