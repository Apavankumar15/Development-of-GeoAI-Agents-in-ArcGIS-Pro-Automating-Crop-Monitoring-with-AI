# ==============================================================================
#  GeoEnviroAI.pyt  —  Environmental Monitoring Agent
#  ArcGIS Pro Python Toolbox  |  Single File  |  One Tool
#  Author : Pavan kumar annepu
#
#  FEATURES:
#   - Auto-detects satellite (Sentinel-2, Landsat-8/9, Landsat-5/7)
#   - Recursive band detection (works with .SAFE folders)
#   - Optional study area boundary (clips all outputs)
#   - Optional Claude AI key (LLM interpretation; rule-based fallback if absent)
#   - Computes selected indices using ArcPy Spatial Analyst
#   - Adds all results to ArcGIS Pro Map View with correct colour ramps
#   - Generates HTML + TXT environmental report with risk flags
# ==============================================================================

import arcpy
import os
import sys
import json
import datetime
import urllib.request
import urllib.error

arcpy.env.overwriteOutput = True


# ==============================================================================
#  BAND PATTERN TABLES
# ==============================================================================

_S2 = {
    "B02":"BLUE",  "B2":"BLUE",
    "B03":"GREEN", "B3":"GREEN",
    "B04":"RED",   "B4":"RED",
    "B05":"REDEDGE1", "B06":"REDEDGE2", "B07":"REDEDGE3",
    "B08":"NIR",   "B8":"NIR",
    "B8A":"NIR_NARROW",
    "B09":"VAPOR",
    "B11":"SWIR1",
    "B12":"SWIR2",
}
_L89 = {
    "B2":"BLUE","B3":"GREEN","B4":"RED","B5":"NIR",
    "B6":"SWIR1","B7":"SWIR2","B10":"THERMAL",
}
_L57 = {
    "B1":"BLUE","B2":"GREEN","B3":"RED","B4":"NIR",
    "B5":"SWIR1","B6":"THERMAL","B7":"SWIR2",
}

_RASTER_EXT = {".tif",".tiff",".img",".jp2",".dat",".vrt"}

# Satellite fingerprints for auto-detection
_SAT_FINGERPRINTS = {
    "Sentinel-2":  ["_B02_","_B03_","_B04_","_B08_","B02.jp2","B04.jp2"],
    "Landsat-8/9": ["LC08_","LC09_","_B4.TIF","_B5.TIF"],
    "Landsat-5/7": ["LT05_","LE07_","_B4.TIF","_B3.TIF"],
}


# ==============================================================================
#  SECTION A — BAND DETECTION (auto satellite + recursive search)
# ==============================================================================

def _all_rasters(root):
    files = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if os.path.splitext(fn)[1].lower() in _RASTER_EXT:
                files.append(os.path.join(dp, fn))
    return files


def auto_detect_satellite(workspace):
    """
    Guess satellite by checking filenames in workspace.
    Returns one of: 'Sentinel-2', 'Landsat-8/9', 'Landsat-5/7'
    """
    files = _all_rasters(workspace)
    names = " ".join(os.path.basename(f).upper() for f in files)

    if any(k.upper() in names for k in ["_B02_","B02.JP2","_B08_","B08.JP2","S2A","S2B","S2C","MSIL2A","MSIL1C"]):
        return "Sentinel-2"
    if any(k.upper() in names for k in ["LC08","LC09","_B10."]):
        return "Landsat-8/9"
    if any(k.upper() in names for k in ["LT05","LE07","LT04"]):
        return "Landsat-5/7"
    # Fallback: count matches per satellite
    scores = {"Sentinel-2":0, "Landsat-8/9":0, "Landsat-5/7":0}
    for sat, patterns in _SAT_FINGERPRINTS.items():
        for p in patterns:
            if p.upper() in names:
                scores[sat] += 1
    return max(scores, key=scores.get)


def detect_bands(workspace, satellite):
    patterns = {"Sentinel-2":_S2, "Landsat-8/9":_L89, "Landsat-5/7":_L57}.get(satellite, _S2)
    all_files = _all_rasters(workspace)

    candidates = {}
    for fpath in all_files:
        stem = os.path.splitext(os.path.basename(fpath))[0].upper()
        for pat in sorted(patterns.keys(), key=len, reverse=True):
            p = pat.upper()
            if stem.endswith("_"+p) or stem == p or ("_"+p+"_") in stem or stem.endswith("."+p):
                candidates.setdefault(patterns[pat], []).append(fpath)
                break

    band_map = {}
    for role, paths in candidates.items():
        def _prio(p):
            u = p.upper()
            return 0 if ("R10M" in u or "10M" in u) else (1 if ("R20M" in u or "20M" in u) else (2 if "R60M" in u else 3))
        band_map[role] = sorted(paths, key=_prio)[0]

    return band_map


def _get(band_map, role):
    p = band_map.get(role)
    if not p:
        raise ValueError(
            "Band '{}' not found. Available: {}".format(role, list(band_map.keys()))
        )
    return p


# ==============================================================================
#  SECTION B — INDEX COMPUTATION
# ==============================================================================

# Registry: index → (required_bands, display_name, colormap, value_range)
INDEX_META = {
    # Vegetation
    "NDVI":  (["NIR","RED"],              "NDVI — Vegetation Health",          "Green",           (-1,1)),
    "EVI":   (["NIR","RED","BLUE"],        "EVI — Enhanced Vegetation",         "Green",           (-1,1)),
    "SAVI":  (["NIR","RED"],              "SAVI — Soil Adjusted Vegetation",    "Yellow to Green", (-1.5,1.5)),
    "NBR":   (["NIR","SWIR2"],            "NBR — Normalized Burn Ratio",        "Red to Green",    (-1,1)),
    "ARVI":  (["NIR","RED","BLUE"],        "ARVI — Atm. Resistant Vegetation",  "Green",           (-1,1)),
    "GNDVI": (["NIR","GREEN"],            "GNDVI — Green NDVI",                 "Green",           (-1,1)),
    # Water
    "NDWI":  (["GREEN","NIR"],            "NDWI — Surface Water",               "Blue",            (-1,1)),
    "MNDWI": (["GREEN","SWIR1"],          "MNDWI — Modified Water Index",       "Blue",            (-1,1)),
    "NDMI":  (["NIR","SWIR1"],            "NDMI — Moisture Index",              "Blue-Purple",     (-1,1)),
    "AWEI":  (["GREEN","SWIR1","NIR","SWIR2"], "AWEI — Water Extraction",       "Blue",            (-2,2)),
    # Soil
    "BSI":   (["SWIR1","RED","NIR","BLUE"],"BSI — Bare Soil Index",             "Brown to White",  (-1,1)),
    "RI":    (["RED","GREEN"],            "RI — Redness / Erosion",             "Red",             (0,10)),
    "NDTI":  (["SWIR1","SWIR2"],          "NDTI — Tillage Index",               "Brown",           (-1,1)),
    "LST":   (["THERMAL"],               "LST — Land Surface Temp (°C)",        "Temperature",     (0,60)),
    # Urban
    "NDBI":  (["SWIR1","NIR"],            "NDBI — Built-up Index",              "Purple",          (-1,1)),
    "IBI":   (["SWIR1","NIR","GREEN","RED"],"IBI — Index-Based Built-up",       "Purple",          (-1,1)),
    "UI":    (["SWIR2","NIR"],            "UI — Urban Index",                   "Purple",          (-1,1)),
    # Fire
    "dNBR":  (["NIR","SWIR2"],            "dNBR — Burn Severity",               "Fire",            (-2,2)),
    "BAI":   (["RED","NIR"],              "BAI — Burn Area Index",              "Fire",            (0,1000)),
    # Ecological
    "RSEI":  (["NIR","RED","GREEN","SWIR1"],"RSEI — Ecological Health Score",   "Red to Green",    (0,1)),
    "NDSI":  (["GREEN","SWIR1"],          "NDSI — Snow Index",                  "Cyan to Blue",    (-1,1)),
}

ALL_INDEX_NAMES = list(INDEX_META.keys())


def _f(path):
    from arcpy.sa import Float, Raster
    return Float(Raster(path))


def _norm(ras):
    """Min-max normalize raster to 0-1."""
    from arcpy.sa import Float
    mn = float(arcpy.GetRasterProperties_management(ras,"MINIMUM").getOutput(0))
    mx = float(arcpy.GetRasterProperties_management(ras,"MAXIMUM").getOutput(0))
    if mx == mn:
        return ras
    return (Float(ras) - Float(mn)) / Float(mx - mn)


def compute_index(name, band_map, output_path, clip_geom=None):
    arcpy.CheckOutExtension("Spatial")
    from arcpy.sa import Float, Power, Ln

    def R(role):
        return _f(_get(band_map, role))

    r = None

    if   name == "NDVI":  nir,red=R("NIR"),R("RED");          r=(nir-red)/(nir+red+Float(1e-10))
    elif name == "EVI":   nir,red,blue=R("NIR"),R("RED"),R("BLUE"); r=Float(2.5)*(nir-red)/(nir+Float(6)*red-Float(7.5)*blue+Float(1))
    elif name == "SAVI":  nir,red=R("NIR"),R("RED");           r=((nir-red)/(nir+red+Float(0.5)))*Float(1.5)
    elif name == "NBR":   nir,s2=R("NIR"),R("SWIR2");          r=(nir-s2)/(nir+s2+Float(1e-10))
    elif name == "ARVI":  nir,red,blue=R("NIR"),R("RED"),R("BLUE"); rb=Float(2)*red-blue; r=(nir-rb)/(nir+rb+Float(1e-10))
    elif name == "GNDVI": nir,g=R("NIR"),R("GREEN");            r=(nir-g)/(nir+g+Float(1e-10))
    elif name == "NDWI":  g,nir=R("GREEN"),R("NIR");            r=(g-nir)/(g+nir+Float(1e-10))
    elif name == "MNDWI": g,s1=R("GREEN"),R("SWIR1");           r=(g-s1)/(g+s1+Float(1e-10))
    elif name == "NDMI":  nir,s1=R("NIR"),R("SWIR1");           r=(nir-s1)/(nir+s1+Float(1e-10))
    elif name == "AWEI":  g,s1,nir,s2=R("GREEN"),R("SWIR1"),R("NIR"),R("SWIR2"); r=Float(4)*(g-s1)-(Float(0.25)*nir+Float(2.75)*s2)
    elif name == "BSI":   s1,red,nir,blue=R("SWIR1"),R("RED"),R("NIR"),R("BLUE"); r=((s1+red)-(nir+blue))/((s1+red)+(nir+blue)+Float(1e-10))
    elif name == "RI":    red,g=R("RED"),R("GREEN");             r=Power(red,2)/(Power(g,3)+Float(1e-10))
    elif name == "NDTI":  s1,s2=R("SWIR1"),R("SWIR2");          r=(s1-s2)/(s1+s2+Float(1e-10))
    elif name == "LST":
        th=R("THERMAL")
        K1,K2=Float(774.8853),Float(1321.0789)
        rad=Float(0.0003342)*th+Float(0.1)
        bt=K2/Ln(K1/rad+Float(1.0))
        r=bt-Float(273.15)
    elif name == "NDBI":  s1,nir=R("SWIR1"),R("NIR");           r=(s1-nir)/(s1+nir+Float(1e-10))
    elif name == "IBI":
        s1,nir,g,red=R("SWIR1"),R("NIR"),R("GREEN"),R("RED")
        ndbi=(s1-nir)/(s1+nir+Float(1e-10))
        savi=((nir-red)/(nir+red+Float(0.5)))*Float(1.5)
        mndwi=(g-s1)/(g+s1+Float(1e-10))
        avg=(savi+mndwi)/Float(2)
        r=(ndbi-avg)/(ndbi+avg+Float(1e-10))
    elif name == "UI":    s2,nir=R("SWIR2"),R("NIR");            r=(s2-nir)/(s2+nir+Float(1e-10))
    elif name == "dNBR":
        nir,s2=R("NIR"),R("SWIR2")
        nbr=(nir-s2)/(nir+s2+Float(1e-10))
        r=nbr-nbr  # zero unless pre/post bands supplied; placeholder
    elif name == "BAI":
        red,nir=R("RED"),R("NIR")
        r=Float(1)/(Power(Float(0.1)-red,2)+Power(Float(0.06)-nir,2)+Float(1e-10))
    elif name == "RSEI":
        nir,red,g,s1=R("NIR"),R("RED"),R("GREEN"),R("SWIR1")
        ndvi=(nir-red)/(nir+red+Float(1e-10))
        ndmi=(nir-s1)/(nir+s1+Float(1e-10))
        try:
            blue=R("BLUE")
            bsi=((s1+red)-(nir+blue))/((s1+red)+(nir+blue)+Float(1e-10))
        except Exception:
            bsi=Float(0)
        raw=(ndvi+ndmi-bsi)/Float(3)
        r=_norm(raw)
    elif name == "NDSI":  g,s1=R("GREEN"),R("SWIR1");            r=(g-s1)/(g+s1+Float(1e-10))
    else:
        raise ValueError("Unknown index: {}".format(name))

    # Optional clip to study area
    if clip_geom:
        from arcpy.sa import ExtractByMask
        r = ExtractByMask(r, clip_geom)

    r.save(output_path)

    try:
        mean = float(arcpy.GetRasterProperties_management(output_path,"MEAN").getOutput(0))
    except Exception:
        mean = 0.0
    return mean


# ==============================================================================
#  SECTION C — INTERPRETATION & RISK DETECTION
# ==============================================================================

_INTERP = {
    "NDVI":  [(-1.0,0.1,"Very Low — bare soil or water"),
              (0.1, 0.3,"Low — sparse / stressed vegetation"),
              (0.3, 0.5,"Moderate — grassland or cropland"),
              (0.5, 0.7,"High — dense healthy vegetation"),
              (0.7, 1.0,"Very High — dense forest / crops")],
    "NDWI":  [(-1.0,0.0,"No open water — dry land"),
              (0.0, 0.3,"Possible moisture / shallow water"),
              (0.3, 1.0,"Open water body / flooded area")],
    "MNDWI": [(-1.0,0.0,"Urban or dry"), (0.0,1.0,"Water / high moisture")],
    "NDMI":  [(-1.0,0.0,"Dry vegetation"),(0.0,0.4,"Moderate moisture"),(0.4,1.0,"High moisture")],
    "BSI":   [(-1.0,0.0,"Vegetation dominant"),
              (0.0, 0.2,"Moderate bare soil"),
              (0.2, 1.0,"High bare soil — degradation risk")],
    "NDBI":  [(-1.0,0.0,"Vegetation dominant"),(0.0,1.0,"Urban / built-up surface")],
    "LST":   [(0,15,"Cool"),(15,30,"Moderate"),(30,40,"Warm — stress / built-up"),(40,100,"Very hot — heat island / fire risk")],
    "NBR":   [(-1.0,-0.1,"High burn severity"),(-0.1,0.1,"Low / unburned"),(0.1,1.0,"Healthy vegetation")],
    "dNBR":  [(-0.5,-0.1,"Post-fire regrowth"),(-0.1,0.1,"Unburned"),
              (0.1,0.27,"Low burn"),(0.27,0.44,"Moderate-low"),(0.44,0.66,"Moderate-high"),(0.66,1.3,"High burn severity")],
    "RSEI":  [(0.0,0.2,"Very Poor ecology"),(0.2,0.4,"Poor"),(0.4,0.6,"Moderate"),
              (0.6,0.8,"Good"),(0.8,1.0,"Excellent ecology")],
}

def _interp(name, val):
    for lo,hi,lbl in _INTERP.get(name,[]):
        if lo <= val < hi:
            return lbl
    return "Value: {:.4f}".format(val)

_RISKS = {
    "DROUGHT":          {"NDVI":("<",0.2), "NDMI":("<",0.0)},
    "FLOOD_RISK":       {"NDWI":(">",0.2)},
    "LAND_DEGRADATION": {"BSI":(">",0.1)},
    "HEAT_STRESS":      {"LST":(">",35.0)},
    "VEGETATION_LOSS":  {"NDVI":("<",0.1)},
    "URBAN_EXPANSION":  {"NDBI":(">",0.0)},
    "FIRE_SEVERITY":    {"dNBR":(">",0.27)},
}

def detect_risks(results):
    risks = []
    for risk, conds in _RISKS.items():
        ok = True
        for idx,(op,thr) in conds.items():
            v = results.get(idx)
            if v is None: ok=False; break
            if op=="<" and not v<thr: ok=False; break
            if op==">" and not v>thr: ok=False; break
        if ok:
            risks.append(risk)
    return risks


# ==============================================================================
#  SECTION D — ADD TO MAP + COLOUR RAMP
# ==============================================================================

_CMAP = {
    "NDVI":"Green","EVI":"Green","SAVI":"Yellow to Green",
    "NBR":"Red to Green","ARVI":"Green","GNDVI":"Green",
    "NDWI":"Blue","MNDWI":"Blue","NDMI":"Blue-Purple","AWEI":"Blue",
    "BSI":"Brown to White","RI":"Red","NDTI":"Brown","LST":"Temperature",
    "NDBI":"Purple","IBI":"Purple","UI":"Purple",
    "dNBR":"Fire","BAI":"Fire","NDSI":"Cyan to Blue","RSEI":"Red to Green",
}

def add_to_map(raster_path, layer_name):
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        m = aprx.activeMap
        if m is None:
            arcpy.AddWarning("  No active map — layer not added.")
            return
        m.addDataFromPath(raster_path)
        # Apply colour ramp
        base = os.path.splitext(os.path.basename(raster_path))[0]
        ramp_name = _CMAP.get(layer_name, "Bathymetric Scale")
        for lyr in m.listLayers():
            if lyr.name == base:
                try:
                    sym = lyr.symbology
                    ramps = aprx.listColorRamps(ramp_name)
                    if ramps:
                        sym.colorizer.colorRamp = ramps[0]
                        sym.colorizer.stretchType = "StdDev"
                        sym.colorizer.standardDeviationsParam = 2.0
                        lyr.symbology = sym
                except Exception:
                    pass
                break
        arcpy.AddMessage("  Added to map: {} [{}]".format(layer_name, ramp_name))
    except Exception as e:
        arcpy.AddWarning("  Map add failed: {}".format(e))


# ==============================================================================
#  SECTION E — LLM AGENT  (Claude API or rule-based fallback)
# ==============================================================================

_SYS_Q = """You are GeoEnviroAI inside ArcGIS Pro. Given a user query, pick the best 2-6 indices from:
{idx_list}

Return ONLY valid JSON — no markdown:
{{"indices":["A","B"],"reasoning":"brief"}}

Rules: ecology/health→NDVI,NDMI,BSI,LST,RSEI | water/flood→NDWI,MNDWI,NDMI | vegetation→NDVI,EVI,SAVI |
soil/erosion→BSI,NDMI,LST | urban/city→NDBI,IBI,LST | fire→NBR,dNBR,BAI | drought→NDVI,NDMI,LST,BSI"""

_SYS_R = """You are an expert environmental scientist inside ArcGIS Pro.
Write a professional environmental monitoring report from computed index values.
Sections: EXECUTIVE SUMMARY | INDEX ANALYSIS | OVERALL CONDITION (GOOD/MODERATE/POOR) | RISK FLAGS | RECOMMENDATIONS.
Plain text, no markdown, clear headings with ===."""


class LLMAgent:
    def __init__(self, api_key=""):
        self.key = (api_key or "").strip()
        self.url = "https://api.anthropic.com/v1/messages"
        self.model = "claude-sonnet-4-20250514"

    def _call(self, system, msg, tokens=800):
        if not self.key:
            return None
        data = json.dumps({"model":self.model,"max_tokens":tokens,
                           "system":system,"messages":[{"role":"user","content":msg}]}).encode()
        req = urllib.request.Request(self.url, data=data,
            headers={"x-api-key":self.key,"anthropic-version":"2023-06-01",
                     "content-type":"application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["content"][0]["text"]
        except Exception as e:
            arcpy.AddWarning("  [LLM] API error: {}".format(e))
            return None

    def parse_query(self, query):
        resp = self._call(_SYS_Q.format(idx_list=", ".join(ALL_INDEX_NAMES)), query, 400)
        if resp:
            try:
                parsed = json.loads(resp.strip().strip("```json").strip("```"))
                indices = parsed.get("indices",[])
                arcpy.AddMessage("  [AI] Selected: {} | {}".format(indices, parsed.get("reasoning","")))
                return indices
            except Exception:
                pass
        return self._rule(query)

    def write_report(self, query, results, risks):
        rows = "\n".join("  {}={:.4f} ({})".format(k,v,_interp(k,v)) for k,v in results.items())
        msg = "Query: {}\nResults:\n{}\nRisks: {}".format(query, rows, ", ".join(risks) or "None")
        resp = self._call(_SYS_R, msg, 1500)
        return resp if resp else self._rule_report(results, risks)

    def _rule(self, q):
        q = q.lower()
        if any(w in q for w in ["ecological","condition","health","composite","overall","integrated"]):
            return ["NDVI","NDMI","BSI","LST","RSEI"]
        if any(w in q for w in ["water","flood","hydro","wetland","river","lake"]):
            return ["NDWI","MNDWI","NDMI"]
        if any(w in q for w in ["vegetation","forest","plant","crop","green","biomass"]):
            return ["NDVI","EVI","SAVI"]
        if any(w in q for w in ["soil","erosion","degradation","desert","bare"]):
            return ["BSI","NDMI","LST","RI"]
        if any(w in q for w in ["urban","city","built","expansion","heat island"]):
            return ["NDBI","IBI","LST"]
        if any(w in q for w in ["fire","burn","wildfire"]):
            return ["NBR","dNBR","BAI"]
        if any(w in q for w in ["drought","stress","temperature","hot"]):
            return ["NDVI","NDMI","LST","BSI"]
        return ["NDVI","NDWI","BSI","RSEI"]

    def _rule_report(self, results, risks):
        rv = results.get("RSEI", results.get("NDVI", 0.4))
        cond = "GOOD" if rv>0.6 else ("MODERATE" if rv>0.35 else "POOR")
        lines = ["=== EXECUTIVE SUMMARY ===",
                 "Environmental analysis complete. {} indices computed. Condition: {}.".format(len(results),cond),"",
                 "=== INDEX ANALYSIS ==="]
        lines += ["  {} = {:.4f}  |  {}".format(k,v,_interp(k,v)) for k,v in results.items()]
        lines += ["","=== OVERALL CONDITION ===","  {}".format(cond),""]
        if risks:
            lines += ["=== RISK FLAGS ==="] + ["  [!] {}".format(r) for r in risks] + [""]
        lines += ["=== RECOMMENDATIONS ===",
                  "  Review raster layers in ArcGIS Pro map view.",
                  "  Compare temporal datasets for change detection."]
        return "\n".join(lines)


# ==============================================================================
#  SECTION F — REPORT WRITER
# ==============================================================================

def write_report(results, risks, out_folder, satellite, ai_text=""):
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sep  = "=" * 68
    rv   = results.get("RSEI", results.get("NDVI", 0.4))
    cond = "GOOD" if rv>0.6 else ("MODERATE" if rv>0.35 else "POOR")

    lines = [sep,
             "  GeoEnviroAI — Environmental Monitoring Report",
             "  Date: {}   |   Satellite: {}".format(now, satellite),
             "  Overall Condition: {}".format(cond),
             sep,"",
             "  INDEX RESULTS","  "+"-"*60]
    for k,v in results.items():
        lines.append("  [{:6s}] {:+.4f}  |  {}".format(k,v,_interp(k,v)))

    if risks:
        lines += ["","  ENVIRONMENTAL RISKS DETECTED","  "+"-"*60]
        lines += ["  [!] {}".format(r) for r in risks]

    if ai_text:
        lines += ["","",sep,"  AI INTERPRETATION (Claude LLM)",sep,"",ai_text]

    lines += ["","",sep,"  Outputs → {}".format(out_folder),"  GeoEnviroAI | ArcGIS Pro + Claude AI",sep]
    body = "\n".join(lines)

    txt  = os.path.join(out_folder, "GeoEnviroAI_Report.txt")
    html = os.path.join(out_folder, "GeoEnviroAI_Report.html")
    with open(txt, "w", encoding="utf-8") as f: f.write(body)

    esc = body.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>\n")
    cond_cls = {"GOOD":"good","MODERATE":"mod","POOR":"poor"}.get(cond,"mod")
    with open(html, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>GeoEnviroAI Report</title>
<style>
body{{font-family:'Courier New',monospace;background:#07101f;color:#e2e8f0;padding:40px;line-height:1.8;max-width:900px;margin:auto}}
h1{{color:#38bdf8;letter-spacing:2px;border-bottom:1px solid #1e3a5f;padding-bottom:10px}}
.good{{color:#22c55e;font-weight:bold}} .mod{{color:#f59e0b;font-weight:bold}} .poor{{color:#ef4444;font-weight:bold}}
pre{{white-space:pre-wrap;font-size:13px}}
</style></head><body>
<h1>&#127757; GeoEnviroAI &mdash; Environmental Monitoring Report</h1>
<p>Satellite: <b>{sat}</b> &nbsp;|&nbsp; Condition: <span class="{cls}">{cond}</span></p>
<pre>{body}</pre></body></html>""".format(sat=satellite, cls=cond_cls, cond=cond, body=esc))

    arcpy.AddMessage("  Report TXT  -> {}".format(txt))
    arcpy.AddMessage("  Report HTML -> {}".format(html))


# ==============================================================================
#  TOOLBOX
# ==============================================================================

class Toolbox:
    def __init__(self):
        self.label       = "GeoEnviroAI"
        self.alias       = "geoenviroai"
        self.description = "AI-Powered Environmental Monitoring Agent for ArcGIS Pro."
        self.tools       = [EnvironmentalMonitoringTool]


# ==============================================================================
#  THE ONE TOOL
# ==============================================================================

class EnvironmentalMonitoringTool:
    def __init__(self):
        self.label       = "Environmental Monitoring Agent"
        self.description = (
            "Auto-detects satellite, selects bands, computes environmental indices, "
            "detects risks, adds results to map and generates a report. "
            "Provide an optional study area boundary to clip outputs. "
            "Optionally add a Claude API key for AI-written interpretation."
        )
        self.canRunInBackground = False

    # ------------------------------------------------------------------
    def getParameterInfo(self):

        # 0 — Input workspace
        p_ws = arcpy.Parameter(
            displayName="Input Band Workspace  (folder or .SAFE folder)",
            name="band_workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input")

        # 1 — Satellite (auto-detect + override)
        p_sat = arcpy.Parameter(
            displayName="Satellite  (Auto-Detect will fill this automatically)",
            name="satellite",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        p_sat.filter.type = "ValueList"
        p_sat.filter.list = ["Auto-Detect","Sentinel-2","Landsat-8/9","Landsat-5/7"]
        p_sat.value       = "Auto-Detect"

        # 2 — Indices multi-select
        p_idx = arcpy.Parameter(
            displayName="Indices to Calculate  (multi-select)",
            name="indices",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        p_idx.filter.type = "ValueList"
        p_idx.filter.list = ALL_INDEX_NAMES
        p_idx.value       = "NDVI;NDWI;BSI;LST;RSEI"

        # 3 — Output folder
        p_out = arcpy.Parameter(
            displayName="Output Folder",
            name="output_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input")

        # 4 — Study area boundary (OPTIONAL)
        p_clip = arcpy.Parameter(
            displayName="Study Area Boundary  [OPTIONAL — clips all outputs]",
            name="study_area",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input")

        # 5 — Natural language query (OPTIONAL — uses LLM to pick indices)
        p_query = arcpy.Parameter(
            displayName="Natural Language Query  [OPTIONAL — AI selects indices for you]",
            name="user_query",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        p_query.value = ""

        # 6 — Claude API key (OPTIONAL)
        p_key = arcpy.Parameter(
            displayName="Claude AI API Key  [OPTIONAL — enables AI report writing]",
            name="api_key",
            datatype="GPStringHidden",
            parameterType="Optional",
            direction="Input")

        # 7 — Add to map
        p_map = arcpy.Parameter(
            displayName="Add all results to Map",
            name="add_to_map",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        p_map.value = True

        return [p_ws, p_sat, p_idx, p_out, p_clip, p_query, p_key, p_map]

    # ------------------------------------------------------------------
    def updateParameters(self, params):
        """Auto-fill satellite when workspace is set."""
        ws  = params[0].valueAsText
        sat = params[1].valueAsText
        if ws and os.path.exists(ws) and (sat == "Auto-Detect" or not params[1].altered):
            try:
                detected = auto_detect_satellite(ws)
                params[1].value = detected
            except Exception:
                pass
        return

    def updateMessages(self, params):
        # Warn if LST selected but satellite has no thermal
        idx_raw = params[2].valueAsText or ""
        sat     = params[1].valueAsText or ""
        if "LST" in idx_raw and "Sentinel" in sat:
            params[2].setWarningMessage(
                "LST requires a Thermal band. "
                "Sentinel-2 does NOT have a thermal band — LST will be skipped automatically."
            )
        else:
            params[2].clearMessage()
        return

    # ------------------------------------------------------------------
    def execute(self, params, messages):
        workspace  = params[0].valueAsText
        satellite  = params[1].valueAsText
        idx_raw    = params[2].valueAsText
        out_folder = params[3].valueAsText
        study_area = params[4].valueAsText   # may be None
        user_query = params[5].valueAsText   # may be empty
        api_key    = params[6].valueAsText or ""
        add_map    = params[7].value

        # ---- Resolve satellite ----
        if satellite == "Auto-Detect" or not satellite:
            satellite = auto_detect_satellite(workspace)
            arcpy.AddMessage("Auto-detected satellite: {}".format(satellite))
        else:
            arcpy.AddMessage("Satellite: {}".format(satellite))

        # ---- Detect bands ----
        arcpy.AddMessage("Scanning bands...")
        band_map = detect_bands(workspace, satellite)
        if not band_map:
            arcpy.AddError("No bands detected. Check workspace path and satellite selection.")
            return
        arcpy.AddMessage("Bands ready: {}".format(list(band_map.keys())))

        # ---- Resolve indices (query or manual) ----
        agent = LLMAgent(api_key)
        if user_query and user_query.strip():
            arcpy.AddMessage("AI parsing query: '{}'".format(user_query))
            indices = agent.parse_query(user_query)
            arcpy.AddMessage("AI selected: {}".format(", ".join(indices)))
        else:
            indices = [i.strip() for i in idx_raw.split(";") if i.strip()]

        arcpy.AddMessage("Indices to compute: {}".format(", ".join(indices)))
        arcpy.AddMessage("-" * 60)

        # ---- Clip geometry ----
        clip_geom = study_area if study_area else None

        # ---- Compute each index ----
        results = {}
        total   = len(indices)
        arcpy.SetProgressor("step", "Computing indices...", 0, total, 1)

        for i, idx in enumerate(indices):
            arcpy.SetProgressorLabel("Computing {} ({}/{})".format(idx, i+1, total))

            # Check required bands
            required = INDEX_META.get(idx, ([],))[0]
            missing  = [b for b in required if b not in band_map]
            if missing:
                arcpy.AddWarning(
                    "  [SKIP] {} — missing bands: {}  "
                    "(not available for {})".format(idx, missing, satellite)
                )
                arcpy.SetProgressorPosition(i+1)
                continue

            out_path = os.path.join(out_folder, "{}.tif".format(idx))
            try:
                val = compute_index(idx, band_map, out_path, clip_geom)
                results[idx] = val
                arcpy.AddMessage(
                    "  [OK] {:6s}  {:+.4f}  |  {}".format(idx, val, _interp(idx, val))
                )
                if add_map:
                    add_to_map(out_path, idx)
            except Exception as e:
                arcpy.AddWarning("  [FAIL] {}: {}".format(idx, e))

            arcpy.SetProgressorPosition(i+1)

        arcpy.ResetProgressor()
        arcpy.AddMessage("-" * 60)

        # ---- Risk detection ----
        risks = detect_risks(results)
        if risks:
            arcpy.AddMessage("RISKS DETECTED: {}".format(", ".join(risks)))
        else:
            arcpy.AddMessage("No environmental risks detected.")

        # ---- AI report ----
        q_for_report = user_query if (user_query and user_query.strip()) else "Environmental monitoring analysis"
        ai_text = agent.write_report(q_for_report, results, risks)

        # ---- Write report ----
        write_report(results, risks, out_folder, satellite, ai_text=ai_text)

        arcpy.AddMessage("=" * 60)
        arcpy.AddMessage("Done.  {} indices computed.  Outputs → {}".format(len(results), out_folder))
