from pydantic import BaseModel

class PresupuestoCreate(BaseModel):
    """Schema para crear presupuesto general"""
    IdArea: int
    MontoAsignado: float
    Periodo: str

class PresupuestoUpdate(BaseModel):
    """Schema para editar presupuesto general"""
    MontoAsignado: float
    Periodo: str

class PresupuestoVerticalCreate(BaseModel):
    """Schema para asignar presupuesto a vertical"""
    IdPresupuesto: int
    IdVertical: int
    MontoAsignado: float