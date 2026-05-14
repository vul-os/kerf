from fastapi import FastAPI

from pyworker.routes import fem, spice, topo, autoroute, cam, ifc, import_kicad, import_kicad_library, import_freecad, rf, mates, pour, rhino3dm as rhino3dm_routes, render as render_routes

# tess route migrated to kerf-tess plugin; import from new location.
try:
    from kerf_tess.routes import router as _tess_router
    _tess_from_plugin = True
except ImportError:
    # Fallback: kerf-tess not installed — route will be absent.
    _tess_router = None
    _tess_from_plugin = False

app = FastAPI()

app.include_router(fem.router, prefix="", tags=["fem"])
app.include_router(spice.router, prefix="", tags=["spice"])
app.include_router(topo.router, prefix="", tags=["topo"])
if _tess_router is not None:
    app.include_router(_tess_router, prefix="", tags=["tess"])
app.include_router(cam.router, prefix="", tags=["cam"])
app.include_router(ifc.router, prefix="", tags=["ifc"])
app.include_router(import_kicad.router, prefix="", tags=["import"])
app.include_router(import_kicad_library.router, prefix="", tags=["import"])
app.include_router(import_freecad.router, prefix="", tags=["import"])
app.include_router(rf.router, prefix="", tags=["rf"])
app.include_router(autoroute.router, prefix="", tags=["autoroute"])
app.include_router(mates.router, prefix="", tags=["mates"])
app.include_router(pour.router, prefix="", tags=["pour"])
app.include_router(rhino3dm_routes.router, prefix="", tags=["rhino3dm"])
app.include_router(render_routes.router, prefix="", tags=["render"])

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}