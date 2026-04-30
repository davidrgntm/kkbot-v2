from contextvars import ContextVar

# Hozirgi sessiya uchun Google Sheet ID sini saqlaydi
sheet_id_ctx = ContextVar("sheet_id_ctx", default=None)