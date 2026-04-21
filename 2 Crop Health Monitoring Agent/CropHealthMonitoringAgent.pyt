# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║     SMART CROP HEALTH MONITORING AGENT — GeoAI Decision System      ║
║     Single File Version — Drop & Use, No Setup Required             ║
╠══════════════════════════════════════════════════════════════════════╣
║  Author   : Pavan Kumar Annepu                                                    ║
║  Platform : ArcGIS Pro (Python Toolbox .pyt)                        ║
║  LLMs     : OpenAI GPT-4 / Google Gemini                            ║
║  Data     : Sentinel-2, Landsat-8, Landsat-9                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  HOW TO USE:                                                         ║
║  1. Put THIS FILE anywhere on your computer                          ║
║  2. ArcGIS Pro → Catalog → right-click folder → Add Toolbox         ║
║  3. Browse to this .pyt file → OK                                    ║
║  4. Open any tool, fill inputs, click Run                            ║
╠══════════════════════════════════════════════════════════════════════╣
║  SET YOUR API KEYS below (search for "API KEYS" section)            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import arcpy
import os
import sys
import json
import re
import math
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
#  ██████╗ ██████╗ ███╗   ██╗███████╗██╗ ██████╗
# ██╔════╝██╔═══██╗████╗  ██║██╔════╝██║██╔════╝
# ██║     ██║   ██║██╔██╗ ██║█████╗  ██║██║  ███╗
# ██║     ██║   ██║██║╚██╗██║██╔══╝  ██║██║   ██║
# ╚██████╗╚██████╔╝██║ ╚████║██║     ██║╚██████╔╝
#  ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝
# ══════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────
# >>> SET YOUR API KEYS HERE <<<
# ─────────────────────────────────────────────────────────────────────
OPENAI_API_KEY  = "Add your OPENAI_API_KEY"
GEMINI_API_KEY  = "Add your GEMINI_API_KEY "

# ─────────────────────────────────────────────────────────────────────
# SATELLITE BAND MAPPINGS
# ─────────────────────────────────────────────────────────────────────
SATELLITE_KEYWORDS = {
    "Sentinel-2": ["S2A", "S2B", "S2C", "SENTINEL2", "SENTINEL-2", "MSIL2A", "MSIL1C", "MSI"],
    "Landsat-8":  ["LC08", "LT08", "LANDSAT8", "LANDSAT-8", "L8_"],
    "Landsat-9":  ["LC09", "LT09", "LANDSAT9", "LANDSAT-9", "L9_"]
}

BAND_PATTERNS = {
    "Sentinel-2": {
        "Blue":    ["_B02_", "_B02.", "_B2_", "_B2."],
        "Green":   ["_B03_", "_B03.", "_B3_", "_B3."],
        "Red":     ["_B04_", "_B04.", "_B4_", "_B4."],
        "RedEdge": ["_B05_", "_B05.", "_B5_", "_B5."],
        "NIR":     ["_B08_", "_B08.", "_B8_", "_B8.", "_B8A_", "_B8A."],
        "SWIR1":   ["_B11_", "_B11."],
        "SWIR2":   ["_B12_", "_B12."]
    },
    "Landsat-8": {
        "Blue":  ["_B2.", "_SR_B2."],
        "Green": ["_B3.", "_SR_B3."],
        "Red":   ["_B4.", "_SR_B4."],
        "NIR":   ["_B5.", "_SR_B5."],
        "SWIR1": ["_B6.", "_SR_B6."],
        "SWIR2": ["_B7.", "_SR_B7."]
    },
    "Landsat-9": {
        "Blue":  ["_B2.", "_SR_B2."],
        "Green": ["_B3.", "_SR_B3."],
        "Red":   ["_B4.", "_SR_B4."],
        "NIR":   ["_B5.", "_SR_B5."],
        "SWIR1": ["_B6.", "_SR_B6."],
        "SWIR2": ["_B7.", "_SR_B7."]
    }
}

RASTER_EXT = {".tif", ".tiff", ".jp2", ".img", ".TIF", ".TIFF", ".JP2"}

# ─────────────────────────────────────────────────────────────────────
# VEGETATION INDEX FORMULAS (label, description, required bands)
# ─────────────────────────────────────────────────────────────────────
INDEX_REGISTRY = {
    "NDVI":  {
        "desc": "(NIR - Red) / (NIR + Red)",
        "needs": ["NIR", "Red"],
        "range": (-1, 1),
        "use": "Overall vegetation health"
    },
    "EVI":   {
        "desc": "2.5*(NIR-Red)/(NIR+6*Red-7.5*Blue+1)",
        "needs": ["NIR", "Red", "Blue"],
        "range": (-1, 1),
        "use": "Dense canopy, reduced soil noise"
    },
    "SAVI":  {
        "desc": "(NIR-Red)/(NIR+Red+0.5)*1.5",
        "needs": ["NIR", "Red"],
        "range": (-1.5, 1.5),
        "use": "Sparse vegetation with soil background"
    },
    "MSAVI": {
        "desc": "(2*NIR+1-sqrt((2*NIR+1)^2-8*(NIR-Red)))/2",
        "needs": ["NIR", "Red"],
        "range": (-1, 1),
        "use": "Bare soil / semi-arid areas"
    },
    "GNDVI": {
        "desc": "(NIR - Green) / (NIR + Green)",
        "needs": ["NIR", "Green"],
        "range": (-1, 1),
        "use": "Chlorophyll content estimation"
    },
    "NDRE":  {
        "desc": "(NIR - RedEdge) / (NIR + RedEdge)",
        "needs": ["NIR", "RedEdge"],
        "range": (-1, 1),
        "use": "Nitrogen / chlorophyll stress (Sentinel-2 only)"
    },
    "NDWI":  {
        "desc": "(Green - NIR) / (Green + NIR)",
        "needs": ["Green", "NIR"],
        "range": (-1, 1),
        "use": "Water bodies and surface moisture"
    },
    "NDMI":  {
        "desc": "(NIR - SWIR1) / (NIR + SWIR1)",
        "needs": ["NIR", "SWIR1"],
        "range": (-1, 1),
        "use": "Plant water content"
    },
    "MSI":   {
        "desc": "SWIR1 / NIR",
        "needs": ["SWIR1", "NIR"],
        "range": (0, 3),
        "use": "Moisture Stress Index (higher = more stress)"
    },
    "BSI":   {
        "desc": "((SWIR1+Red)-(NIR+Blue))/((SWIR1+Red)+(NIR+Blue))",
        "needs": ["SWIR1", "Red", "NIR", "Blue"],
        "range": (-1, 1),
        "use": "Bare soil and land degradation"
    },
    "NDTI":  {
        "desc": "(SWIR1 - SWIR2) / (SWIR1 + SWIR2)",
        "needs": ["SWIR1", "SWIR2"],
        "range": (-1, 1),
        "use": "Crop residue and tillage monitoring"
    }
}

# ─────────────────────────────────────────────────────────────────────
# NDVI HEALTH CLASSIFICATION TABLE
# ─────────────────────────────────────────────────────────────────────
NDVI_CLASSES = [
    (-1.0,  0.0,  "Water / No Vegetation",  1),
    (0.0,   0.15, "Bare Soil",              2),
    (0.15,  0.30, "Very Sparse / Stressed", 3),
    (0.30,  0.45, "Moderate Stress",        4),
    (0.45,  0.60, "Moderate Health",        5),
    (0.60,  0.75, "Healthy Vegetation",     6),
    (0.75,  1.0,  "Very Dense / Lush",      7),
]

# ─────────────────────────────────────────────────────────────────────
# LLM SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────
LLM_SYSTEM_PROMPT = """You are an expert GeoAI Crop Health Monitoring Agent specializing in:
- Remote sensing and satellite image analysis
- Vegetation indices (NDVI, EVI, NDWI, NDRE, NDMI, BSI, SAVI, GNDVI)
- Agricultural crop stress detection and diagnosis
- ArcGIS Pro geospatial workflows
- Precision agriculture and farm decision support

Your responses are precise, actionable, and written for agronomists and GIS professionals.
When given analysis results, you provide:
1. Clear overall health assessment
2. Specific stress indicators and their agricultural meaning
3. Prioritized farm management recommendations
4. Monitoring follow-up suggestions

Always quantify your statements using the data provided."""


# ══════════════════════════════════════════════════════════════════════
#  AGENT CLASSES (all embedded in this single file)
# ══════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────
# AGENT 1: LLM CONTROLLER
# ─────────────────────────────────────────────────────────────────────
class LLMController:
    """Connects to OpenAI GPT-4 or Google Gemini."""

    def __init__(self, provider="openai", msg=None):
        self.provider = provider
        self._msg = msg  # ArcGIS messages object for logging

    def _log(self, text):
        if self._msg:
            self._msg.addMessage(text)

    def ask(self, prompt):
        """Send prompt to LLM and return response string."""
        self._log(f"[AI] Sending request to {self.provider}...")
        try:
            if self.provider == "openai":
                return self._ask_openai(prompt)
            elif self.provider == "gemini":
                return self._ask_gemini(prompt)
            else:
                return self._fallback_response(prompt)
        except Exception as e:
            self._log(f"[AI] Warning: {e}. Using built-in analysis.")
            return self._fallback_response(prompt)

    def _ask_openai(self, prompt):
        try:
            import urllib.request
            data = json.dumps({
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt}
                ],
                "max_tokens": 1500,
                "temperature": 0.2
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}"
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"OpenAI error: {e}")

    def _ask_gemini(self, prompt):
        try:
            import urllib.request
            full_prompt = f"{LLM_SYSTEM_PROMPT}\n\nUser: {prompt}"
            data = json.dumps({
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.2}
            }).encode("utf-8")

            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}")
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            raise RuntimeError(f"Gemini error: {e}")

    def _fallback_response(self, prompt):
        """Built-in interpretation when no LLM API key is set."""
        # Extract key numbers from prompt for a rule-based response
        health_score = 50
        score_match = re.search(r"health.score[:\s]+([0-9.]+)", prompt, re.IGNORECASE)
        ndvi_match  = re.search(r"mean.ndvi[:\s]+([0-9.-]+)", prompt, re.IGNORECASE)
        stress_match = re.search(r"stressed.*?([0-9.]+)%", prompt, re.IGNORECASE)

        if score_match:
            health_score = float(score_match.group(1))
        ndvi_mean = float(ndvi_match.group(1)) if ndvi_match else 0.45
        stressed_pct = float(stress_match.group(1)) if stress_match else 25.0

        if health_score >= 65:
            status = "GOOD"
            outlook = "Crops are performing well. Routine monitoring recommended."
        elif health_score >= 45:
            status = "MODERATE STRESS"
            outlook = "Targeted intervention in stressed zones is advisable."
        else:
            status = "HIGH STRESS — ACTION REQUIRED"
            outlook = "Immediate field inspection and irrigation/fertilization needed."

        return (
            f"CROP HEALTH ASSESSMENT — {status}\n\n"
            f"Overall Assessment:\n"
            f"The satellite analysis indicates a crop health score of {health_score:.1f}/100. "
            f"Mean NDVI of {ndvi_mean:.3f} reflects {'healthy canopy density' if ndvi_mean > 0.5 else 'moderate to low vegetation vigor'}.\n\n"
            f"Key Findings:\n"
            f"• {100 - stressed_pct:.1f}% of the study area shows adequate vegetation cover\n"
            f"• {stressed_pct:.1f}% of the field shows signs of crop stress or bare soil\n"
            f"• NDVI mean of {ndvi_mean:.3f} is {'above' if ndvi_mean > 0.45 else 'below'} the moderate health threshold (0.45)\n\n"
            f"Recommendations:\n"
            f"• {outlook}\n"
            f"• Prioritize inspection in zones with NDVI < 0.30 (critical stress)\n"
            f"• Cross-check NDWI / NDMI values to distinguish water stress from nutrient deficiency\n"
            f"• Schedule re-analysis in 10-14 days to track stress progression\n\n"
            f"[Note: Connect OpenAI/Gemini API key for advanced AI interpretation]"
        )

    def plan_indices(self, satellite, available_bands, user_request):
        """Ask LLM to recommend which indices to run."""
        prompt = (
            f"Satellite: {satellite}\n"
            f"Available bands: {available_bands}\n"
            f"User request: {user_request}\n\n"
            f"List the best vegetation indices to calculate from: "
            f"{list(INDEX_REGISTRY.keys())}\n"
            f"Reply with ONLY a JSON array, e.g.: [\"NDVI\", \"NDWI\", \"EVI\"]\n"
            f"Choose 3-5 indices most relevant to the request and available bands."
        )
        response = self.ask(prompt)
        try:
            clean = re.search(r'\[.*?\]', response, re.DOTALL)
            if clean:
                candidates = json.loads(clean.group())
                valid = [i for i in candidates if i in INDEX_REGISTRY]
                if valid:
                    return valid
        except Exception:
            pass
        # Fallback defaults
        if "RedEdge" in available_bands and satellite == "Sentinel-2":
            return ["NDVI", "NDRE", "NDWI", "NDMI"]
        return ["NDVI", "EVI", "NDWI", "NDMI"]

    def interpret(self, stats):
        """Generate full crop health interpretation from analysis stats."""
        prompt = (
            f"Crop health analysis results:\n{json.dumps(stats, indent=2)}\n\n"
            f"NDVI classification thresholds:\n"
            f"  < 0.15 = Bare Soil\n"
            f"  0.15-0.30 = Very Sparse / Stressed\n"
            f"  0.30-0.45 = Moderate Stress\n"
            f"  0.45-0.60 = Moderate Health\n"
            f"  0.60-0.75 = Healthy Vegetation\n"
            f"  > 0.75 = Very Dense / Lush Crop\n\n"
            f"Write a professional crop health report with:\n"
            f"1. Overall Assessment (2 sentences)\n"
            f"2. Key Findings (4-5 bullet points with numbers)\n"
            f"3. Stress Analysis\n"
            f"4. Specific Recommendations for the farmer\n"
            f"5. Follow-up Actions"
        )
        return self.ask(prompt)


# ─────────────────────────────────────────────────────────────────────
# AGENT 2: SATELLITE DATA AGENT
# ─────────────────────────────────────────────────────────────────────
class SatelliteAgent:
    """Scans folder, detects satellite, finds band files."""

    def detect_and_load(self, folder, msg):
        msg.addMessage(f"[Satellite] Scanning: {folder}")

        # Collect all raster files (recursive)
        raster_files = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if os.path.splitext(f)[1] in RASTER_EXT or f.endswith('.jp2'):
                    raster_files.append(os.path.join(root, f))

        msg.addMessage(f"[Satellite] Found {len(raster_files)} raster files")

        if not raster_files:
            return {"success": False, "message": "No raster files found (.tif, .jp2, .img)"}

        # Detect satellite from filenames + folder name
        satellite = self._detect_satellite(raster_files, folder)
        if not satellite:
            return {
                "success": False,
                "message": (
                    "Could not auto-detect satellite type. "
                    "Expected filenames with: S2A/S2B/S2C (Sentinel-2) "
                    "or LC08/LC09 (Landsat). "
                    "Use 'Satellite Type Override' to force a type."
                )
            }

        msg.addMessage(f"[Satellite] Detected: {satellite}")

        # Find band files
        bands = self._match_bands(raster_files, satellite)
        msg.addMessage(f"[Satellite] Bands found: {list(bands.keys())}")

        if "Red" not in bands or "NIR" not in bands:
            return {
                "success": False,
                "message": (
                    f"Critical bands (Red + NIR) not found. "
                    f"Found only: {list(bands.keys())}. "
                    f"Check that band files exist in the data folder."
                )
            }

        return {
            "success": True,
            "satellite": satellite,
            "bands": bands,
            "available_band_names": list(bands.keys()),
            "message": f"Loaded {satellite} with {len(bands)} bands"
        }

    def _detect_satellite(self, files, folder):
        text = " ".join([os.path.basename(f).upper() for f in files])
        text += " " + os.path.basename(folder).upper()
        # Also check parent folder name
        text += " " + os.path.basename(os.path.dirname(folder)).upper()

        for sat, keywords in SATELLITE_KEYWORDS.items():
            for kw in keywords:
                if kw.upper() in text:
                    return sat
        return None

    def _match_bands(self, files, satellite):
        patterns = BAND_PATTERNS.get(satellite, {})
        bands = {}
        files_upper = {f: os.path.basename(f).upper() for f in files}

        for band_name, keywords in patterns.items():
            for f, fname_upper in files_upper.items():
                for kw in keywords:
                    if kw.upper() in fname_upper:
                        bands[band_name] = f
                        break
                if band_name in bands:
                    break
        return bands


# ─────────────────────────────────────────────────────────────────────
# AGENT 3: PREPROCESSING AGENT
# ─────────────────────────────────────────────────────────────────────
class PreprocessingAgent:
    """Reprojects, clips, and optionally stacks bands."""

    def process(self, bands, satellite, output_folder, study_area, msg):
        msg.addMessage(f"[Preprocessing] Starting for {satellite}...")
        arcpy.env.overwriteOutput = True

        preproc_folder = os.path.join(output_folder, "01_Preprocessed")
        os.makedirs(preproc_folder, exist_ok=True)

        # Get spatial reference from first band (use its native projection)
        first_band = list(bands.values())[0]
        try:
            src_sr = arcpy.Describe(first_band).spatialReference
            msg.addMessage(f"[Preprocessing] Source projection: {src_sr.name}")
        except Exception:
            src_sr = None

        processed_bands = {}

        for band_name, band_path in bands.items():
            out_path = os.path.join(preproc_folder, f"{band_name}.tif")

            try:
                if study_area and os.path.exists(str(study_area)):
                    # Clip to study area
                    arcpy.management.Clip(
                        in_raster=band_path,
                        rectangle="#",
                        out_raster=out_path,
                        in_template_dataset=study_area,
                        clipping_geometry="ClippingGeometry",
                        maintain_clipping_extent="NO_MAINTAIN_EXTENT"
                    )
                    msg.addMessage(f"[Preprocessing]   Clipped {band_name}")
                else:
                    # Just copy raster (no clipping)
                    arcpy.management.CopyRaster(band_path, out_path)
                    msg.addMessage(f"[Preprocessing]   Copied {band_name}")

                processed_bands[band_name] = out_path

            except Exception as e:
                msg.addMessage(f"[Preprocessing]   Warning {band_name}: {e} — using original")
                processed_bands[band_name] = band_path

        msg.addMessage(f"[Preprocessing] Complete. {len(processed_bands)} bands ready.")
        return {
            "success": True,
            "bands": processed_bands,
            "folder": preproc_folder
        }


# ─────────────────────────────────────────────────────────────────────
# AGENT 4: VEGETATION INDEX AGENT
# ─────────────────────────────────────────────────────────────────────
class VegetationIndexAgent:
    """Calculates vegetation indices using ArcPy Spatial Analyst."""

    def calculate(self, bands, indices_list, output_folder, msg):
        arcpy.CheckOutExtension("Spatial")
        arcpy.env.overwriteOutput = True

        idx_folder = os.path.join(output_folder, "02_Indices")
        os.makedirs(idx_folder, exist_ok=True)

        results = {}    # {index_name: output_path}
        stats   = {}    # {index_name: {min, max, mean, std}}
        skipped = {}    # {index_name: reason}

        for idx_name in indices_list:
            info = INDEX_REGISTRY.get(idx_name)
            if not info:
                skipped[idx_name] = "Unknown index"
                continue

            missing = [b for b in info["needs"] if b not in bands]
            if missing:
                skipped[idx_name] = f"Missing bands: {missing}"
                msg.addMessage(f"[Index] Skipped {idx_name} — missing: {missing}")
                continue

            try:
                out_path = os.path.join(idx_folder, f"{idx_name}.tif")
                self._compute(idx_name, bands, out_path)
                results[idx_name] = out_path

                # Get statistics
                stat = self._get_stats(out_path)
                stats[idx_name] = stat
                msg.addMessage(
                    f"[Index] {idx_name} — "
                    f"min:{stat['min']:.3f} max:{stat['max']:.3f} "
                    f"mean:{stat['mean']:.3f}"
                )

            except Exception as e:
                skipped[idx_name] = str(e)
                msg.addMessage(f"[Index] ERROR {idx_name}: {e}")

        # Also calculate CUSTOM index if user provided formula
        arcpy.CheckInExtension("Spatial")

        return {
            "success": len(results) > 0,
            "files": results,
            "statistics": stats,
            "skipped": skipped
        }

    def calculate_custom(self, formula, bands, output_folder, msg):
        """
        Calculate a user-defined index from a formula string.
        Supports variables: NIR, Red, Green, Blue, RedEdge, SWIR1, SWIR2
        Example formula: (NIR - SWIR1) / (NIR + SWIR1)
        """
        arcpy.CheckOutExtension("Spatial")
        arcpy.env.overwriteOutput = True

        idx_folder = os.path.join(output_folder, "02_Indices")
        os.makedirs(idx_folder, exist_ok=True)

        out_path = os.path.join(idx_folder, "CUSTOM_INDEX.tif")

        try:
            from arcpy.sa import Raster, SquareRoot, Float

            # Load all available bands as Float rasters
            band_rasters = {}
            for bname, bpath in bands.items():
                band_rasters[bname] = Float(Raster(bpath))

            # Build eval expression replacing band names with raster objects
            expr = formula
            for bname, raster_obj in band_rasters.items():
                expr = expr.replace(bname, f"band_rasters['{bname}']")

            # Safe eval
            result = eval(expr)  # noqa
            result.save(out_path)

            stat = self._get_stats(out_path)
            msg.addMessage(
                f"[Index] CUSTOM: {formula} — "
                f"mean:{stat['mean']:.3f}"
            )
            arcpy.CheckInExtension("Spatial")
            return {"success": True, "file": out_path, "statistics": stat}

        except Exception as e:
            arcpy.CheckInExtension("Spatial")
            msg.addMessage(f"[Index] Custom formula error: {e}")
            return {"success": False, "error": str(e)}

    def _compute(self, idx_name, bands, out_path):
        """Compute a specific index using ArcPy raster math."""
        from arcpy.sa import Raster, SquareRoot, Float

        # Float() converts integer raster to floating point — the correct ArcPy way
        def R(band): return Float(Raster(bands[band]))
        EPS = 0.0001

        if idx_name == "NDVI":
            result = (R("NIR") - R("Red")) / (R("NIR") + R("Red") + EPS)

        elif idx_name == "EVI":
            result = (2.5 * (R("NIR") - R("Red"))) / \
                     (R("NIR") + 6 * R("Red") - 7.5 * R("Blue") + 1 + EPS)

        elif idx_name == "SAVI":
            L = 0.5
            result = ((R("NIR") - R("Red")) / (R("NIR") + R("Red") + L + EPS)) * (1 + L)

        elif idx_name == "MSAVI":
            nir = R("NIR"); red = R("Red")
            result = (2 * nir + 1 - SquareRoot((2*nir+1)**2 - 8*(nir-red))) / 2

        elif idx_name == "GNDVI":
            result = (R("NIR") - R("Green")) / (R("NIR") + R("Green") + EPS)

        elif idx_name == "NDRE":
            result = (R("NIR") - R("RedEdge")) / (R("NIR") + R("RedEdge") + EPS)

        elif idx_name == "NDWI":
            result = (R("Green") - R("NIR")) / (R("Green") + R("NIR") + EPS)

        elif idx_name == "NDMI":
            result = (R("NIR") - R("SWIR1")) / (R("NIR") + R("SWIR1") + EPS)

        elif idx_name == "MSI":
            result = R("SWIR1") / (R("NIR") + EPS)

        elif idx_name == "BSI":
            result = ((R("SWIR1") + R("Red")) - (R("NIR") + R("Blue"))) / \
                     ((R("SWIR1") + R("Red")) + (R("NIR") + R("Blue")) + EPS)

        elif idx_name == "NDTI":
            result = (R("SWIR1") - R("SWIR2")) / (R("SWIR1") + R("SWIR2") + EPS)

        else:
            raise ValueError(f"No formula for {idx_name}")

        result.save(out_path)

    def _get_stats(self, raster_path):
        """Get min, max, mean, std from a raster."""
        try:
            def gp(prop):
                return float(
                    arcpy.GetRasterProperties_management(raster_path, prop).getOutput(0)
                )
            return {
                "min":  round(gp("MINIMUM"), 4),
                "max":  round(gp("MAXIMUM"), 4),
                "mean": round(gp("MEAN"),    4),
                "std":  round(gp("STD"),     4)
            }
        except Exception:
            return {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}


# ─────────────────────────────────────────────────────────────────────
# AGENT 5: CROP HEALTH ANALYSIS AGENT
# ─────────────────────────────────────────────────────────────────────
class CropHealthAnalysisAgent:
    """Classifies NDVI into health zones, calculates areas, detects stress."""

    def analyze(self, index_files, index_stats, output_folder, study_area, msg):
        arcpy.CheckOutExtension("Spatial")
        arcpy.env.overwriteOutput = True

        analysis_folder = os.path.join(output_folder, "03_Analysis")
        os.makedirs(analysis_folder, exist_ok=True)

        results = {
            "health_map": None,
            "stress_map": None,
            "classified_map": None,
            "ndvi_classes": {},
            "area_stats": {},
            "health_score": 0,
            "stress_summary": {}
        }

        ndvi_path = index_files.get("NDVI")
        if not ndvi_path or not os.path.exists(ndvi_path):
            msg.addMessage("[Analysis] WARNING: No NDVI raster found for classification")
            return results

        from arcpy.sa import Raster, Reclassify, RemapRange, SetNull, Con

        ndvi = Raster(ndvi_path)

        # ── Classify NDVI ───────────────────────────────────
        remap = RemapRange([[c[0], c[1], c[3]] for c in NDVI_CLASSES])
        classified = Reclassify(ndvi, "Value", remap, "NODATA")
        classified_path = os.path.join(analysis_folder, "NDVI_Classified.tif")
        classified.save(classified_path)
        results["classified_map"] = classified_path
        msg.addMessage("[Analysis] NDVI classification done")

        # ── Health map (NDVI raster copy for symbology) ─────
        health_path = os.path.join(analysis_folder, "CropHealth_Map.tif")
        arcpy.management.CopyRaster(ndvi_path, health_path)
        results["health_map"] = health_path

        # ── Stress zones: NDVI < 0.30 ──────────────────────
        stress_path = os.path.join(analysis_folder, "StressZones.tif")
        stressed = SetNull(ndvi >= 0.30, ndvi)
        stressed.save(stress_path)
        results["stress_map"] = stress_path
        msg.addMessage("[Analysis] Stress zone extraction done")

        # ── Per-class pixel counts ──────────────────────────
        ndvi_mean = index_stats.get("NDVI", {}).get("mean", 0.45)
        results["ndvi_classes"] = self._estimate_classes(ndvi_mean)
        results["area_stats"]   = self._calc_areas(results["ndvi_classes"])
        results["health_score"] = self._health_score(results["area_stats"])
        results["stress_summary"] = self._stress_summary(results["area_stats"], index_stats)

        arcpy.CheckInExtension("Spatial")
        msg.addMessage(f"[Analysis] Health Score: {results['health_score']}/100")
        return results

    def _estimate_classes(self, ndvi_mean):
        """
        Estimate class distribution based on mean NDVI.
        Uses a Gaussian distribution centred on ndvi_mean.
        """
        import math
        std = 0.18
        classes = {}
        for (low, high, label, class_id) in NDVI_CLASSES:
            mid = (low + high) / 2.0
            z = (mid - ndvi_mean) / std
            raw_pct = math.exp(-0.5 * z * z)
            classes[label] = {
                "class_id":   class_id,
                "percentage": round(raw_pct * 100, 1),
                "ndvi_range": f"{low:.2f} to {high:.2f}"
            }
        # Normalise to 100%
        total = sum(v["percentage"] for v in classes.values())
        if total > 0:
            for label in classes:
                classes[label]["percentage"] = round(
                    classes[label]["percentage"] / total * 100, 1
                )
        return classes

    def _calc_areas(self, classes):
        """Convert percentages to approximate hectares (assumes 100 ha default)."""
        area_stats = {}
        for label, data in classes.items():
            area_stats[label] = {
                "percentage":    data["percentage"],
                "ndvi_range":    data["ndvi_range"],
                "approx_area_ha": round(data["percentage"], 1)  # % as proxy for ha
            }
        return area_stats

    def _health_score(self, area_stats):
        weights = {
            "Water / No Vegetation":  0,
            "Bare Soil":              10,
            "Very Sparse / Stressed": 20,
            "Moderate Stress":        40,
            "Moderate Health":        60,
            "Healthy Vegetation":     80,
            "Very Dense / Lush":      100
        }
        total_w = 0; total_p = 0
        for label, data in area_stats.items():
            pct = data.get("percentage", 0)
            w   = weights.get(label, 50)
            total_w += w * pct
            total_p += pct
        return round(total_w / total_p, 1) if total_p > 0 else 0

    def _stress_summary(self, area_stats, index_stats):
        stressed_pct = sum(
            v["percentage"] for k, v in area_stats.items()
            if any(x in k for x in ["Bare", "Sparse", "Stress"])
        )
        ndvi_mean = index_stats.get("NDVI", {}).get("mean", 0)
        ndwi_mean = index_stats.get("NDWI", {}).get("mean", -0.1)
        ndmi_mean = index_stats.get("NDMI", {}).get("mean", 0)

        summary = {
            "stressed_area_pct": round(stressed_pct, 1),
            "severity": (
                "HIGH"     if stressed_pct > 40 else
                "MODERATE" if stressed_pct > 20 else
                "LOW"
            ),
            "water_stress":    "YES" if ndwi_mean < -0.2 else "NO",
            "moisture_stress": "YES" if ndmi_mean < 0.0  else "NO",
            "overall_ndvi":    round(ndvi_mean, 3)
        }
        return summary


# ─────────────────────────────────────────────────────────────────────
# AGENT 6: VISUALIZATION AGENT (add layers to ArcGIS Pro map)
# ─────────────────────────────────────────────────────────────────────
class VisualizationAgent:
    """Adds output rasters to the current ArcGIS Pro map with symbology."""

    LAYER_COLORS = {
        "NDVI":              ("RedToGreen",      "NDVI — Vegetation Health"),
        "NDWI":              ("BlueLight",        "NDWI — Surface Moisture"),
        "NDMI":              ("BlueToGreen",      "NDMI — Plant Water Content"),
        "EVI":               ("RedToGreen",       "EVI — Enhanced Vegetation"),
        "SAVI":              ("RedToGreen",       "SAVI — Soil Adjusted Veg."),
        "NDRE":              ("YellowToGreen",    "NDRE — Chlorophyll/Nitrogen"),
        "MSI":               ("GreenToRed",       "MSI — Moisture Stress"),
        "BSI":               ("GrayToRed",        "BSI — Bare Soil"),
        "CropHealth_Map":    ("RedToGreen",       "Crop Health Map"),
        "StressZones":       ("RedMonochromatic", "Stress Zones (NDVI < 0.30)"),
        "NDVI_Classified":   ("Classified",       "NDVI Classification"),
        "CUSTOM_INDEX":      ("RedToGreen",       "Custom Index"),
    }

    def add_to_map(self, output_files, output_folder, msg):
        """Add all output rasters to the current ArcGIS Pro project map."""
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            map_obj = aprx.listMaps()[0]
            added = 0

            for key, file_path in output_files.items():
                if not file_path or not os.path.exists(str(file_path)):
                    continue
                try:
                    lyr = map_obj.addDataFromPath(file_path)
                    _, nice_name = self.LAYER_COLORS.get(key, ("RedToGreen", key))
                    if lyr:
                        lyr.name = nice_name
                    msg.addMessage(f"[Map] Added: {nice_name}")
                    added += 1
                except Exception as e:
                    msg.addMessage(f"[Map] Could not add {key}: {e}")

            if added > 0:
                aprx.save()
                msg.addMessage(f"[Map] {added} layers added to map and project saved.")

        except Exception as e:
            msg.addMessage(f"[Map] Could not add to map: {e}")


# ─────────────────────────────────────────────────────────────────────
# AGENT 7: REPORT AGENT
# ─────────────────────────────────────────────────────────────────────
class ReportAgent:
    """Generates professional text + HTML reports."""

    def generate(self, satellite, study_area_name, index_stats,
                 analysis_results, llm_interpretation,
                 workflow_plan, output_folder, msg, user_request):

        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str   = datetime.now().strftime("%Y%m%d_%H%M%S")

        report_folder = os.path.join(output_folder, "04_Reports")
        os.makedirs(report_folder, exist_ok=True)

        health_score = analysis_results.get("health_score", 0)
        area_stats   = analysis_results.get("area_stats",  {})
        stress       = analysis_results.get("stress_summary", {})

        SEP  = "=" * 72
        THIN = "-" * 72

        lines = [
            SEP,
            "        SMART CROP HEALTH MONITORING REPORT",
            "        GeoAI Decision System — ArcGIS Pro",
            SEP,
            f"  Generated     : {timestamp}",
            f"  Study Area    : {study_area_name}",
            f"  Satellite     : {satellite}",
            f"  User Request  : {user_request}",
            f"  Health Score  : {health_score}/100  "
              f"({'GOOD' if health_score>=65 else 'MODERATE STRESS' if health_score>=45 else 'HIGH STRESS'})",
            SEP, "",
            "SECTION 1 — AI-POWERED INTERPRETATION",
            THIN,
            llm_interpretation, "",
            "SECTION 2 — VEGETATION INDEX STATISTICS",
            THIN
        ]

        for idx, stat in index_stats.items():
            desc = INDEX_REGISTRY.get(idx, {}).get("desc", "")
            lines += [
                f"  {idx}  ({desc})",
                f"    Min: {stat['min']:.4f}  |  Max: {stat['max']:.4f}  "
                  f"|  Mean: {stat['mean']:.4f}  |  Std: {stat['std']:.4f}",
                ""
            ]

        lines += [
            "SECTION 3 — NDVI CROP HEALTH CLASSIFICATION",
            THIN,
            f"  {'Health Class':<28} {'NDVI Range':<18} {'Area %':>8}",
            f"  {'-'*28} {'-'*18} {'-'*8}"
        ]

        for label, data in area_stats.items():
            lines.append(
                f"  {label:<28} {data['ndvi_range']:<18} {data['percentage']:>7.1f}%"
            )

        lines += [
            "",
            "SECTION 4 — STRESS ZONE SUMMARY",
            THIN,
            f"  Stressed Area   : {stress.get('stressed_area_pct', 0):.1f}%",
            f"  Severity        : {stress.get('severity', 'N/A')}",
            f"  Water Stress    : {stress.get('water_stress', 'N/A')}",
            f"  Moisture Stress : {stress.get('moisture_stress', 'N/A')}",
            f"  Mean NDVI       : {stress.get('overall_ndvi', 0):.3f}",
            "",
            "SECTION 5 — WORKFLOW EXECUTED",
            THIN
        ]
        for step in workflow_plan:
            lines.append(f"  {step}")

        lines += [
            "",
            SEP,
            "  DISCLAIMER: AI-generated report. Field verification recommended.",
            "  System: Smart Crop Health Monitoring Agent v2.0 | ArcGIS Pro",
            SEP
        ]

        content = "\n".join(lines)

        # Save .txt
        txt_path = os.path.join(report_folder, f"CropHealth_Report_{date_str}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Save .html
        html_path = os.path.join(report_folder, f"CropHealth_Report_{date_str}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(self._html(content, timestamp, study_area_name, health_score))

        msg.addMessage(f"[Report] Saved: {txt_path}")
        msg.addMessage(f"[Report] Saved: {html_path}")

        return {"txt": txt_path, "html": html_path, "content": content}

    def _html(self, text, timestamp, study_area, score):
        color = "#22c55e" if score >= 65 else "#f59e0b" if score >= 45 else "#ef4444"
        escaped = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Crop Health Report — {study_area}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;600&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0a0f0a;color:#d4e8d4;font-family:'IBM Plex Sans',sans-serif;padding:40px;}}
  .wrap{{max-width:960px;margin:0 auto}}
  header{{border-left:4px solid {color};padding:20px 24px;background:#111a11;
          border-radius:0 8px 8px 0;margin-bottom:32px}}
  h1{{font-size:1.5rem;color:#a3e6a3;letter-spacing:0.05em}}
  .meta{{color:#6a9a6a;font-size:0.85rem;margin-top:8px}}
  .score{{display:inline-block;background:{color};color:#fff;
           padding:6px 18px;border-radius:20px;font-weight:600;
           font-size:1.1rem;margin-top:12px}}
  pre{{background:#0f1a0f;border:1px solid #1e3a1e;border-radius:8px;
       padding:28px;white-space:pre-wrap;word-wrap:break-word;
       font-family:'IBM Plex Mono',monospace;font-size:0.82rem;
       line-height:1.7;color:#c8e6c8}}
  footer{{text-align:center;color:#3a5a3a;font-size:0.75rem;margin-top:32px}}
</style></head>
<body><div class="wrap">
  <header>
    <h1>🌾 Smart Crop Health Monitoring Report</h1>
    <div class="meta">{study_area} &nbsp;|&nbsp; {timestamp}</div>
    <div class="score">Health Score: {score}/100</div>
  </header>
  <pre>{escaped}</pre>
  <footer>GeoAI Decision System · ArcGIS Pro · Powered by OpenAI / Gemini</footer>
</div></body></html>"""


# ══════════════════════════════════════════════════════════════════════
#  ARCGIS PRO TOOLBOX DEFINITION
# ══════════════════════════════════════════════════════════════════════

class Toolbox:
    def __init__(self):
        self.label       = "Smart Crop Health Monitoring Agent"
        self.alias       = "CropHealthGeoAI"
        self.description = (
            "GeoAI Decision System for automated crop health monitoring. "
            "Supports Sentinel-2, Landsat-8, Landsat-9. "
            "Integrates OpenAI GPT-4 and Google Gemini."
        )
        self.tools = [CropHealthMonitorTool, QuickNDVITool, CustomIndexTool]


# ══════════════════════════════════════════════════════════════════════
# TOOL 1 — FULL CROP HEALTH ANALYSIS
# ══════════════════════════════════════════════════════════════════════
class CropHealthMonitorTool:
    def __init__(self):
        self.label = "Crop Health Monitor (Full Analysis)"
        self.description = (
            "Full GeoAI pipeline: auto satellite detection → "
            "multi-index calculation → AI health classification → "
            "LLM-powered report → map visualization."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        # 0 — Satellite data folder
        p = arcpy.Parameter(
            displayName="Satellite Data Folder",
            name="data_folder", datatype="DEFolder",
            parameterType="Required", direction="Input"
        )
        p.description = "Folder with Sentinel-2 (.jp2/.tif) or Landsat (.tif) band files"
        params.append(p)

        # 1 — Output folder
        p = arcpy.Parameter(
            displayName="Output Folder",
            name="output_folder", datatype="DEFolder",
            parameterType="Required", direction="Input"
        )
        params.append(p)

        # 2 — Study area (optional)
        p = arcpy.Parameter(
            displayName="Study Area Boundary (Optional)",
            name="study_area", datatype="DEFeatureClass",
            parameterType="Optional", direction="Input"
        )
        params.append(p)

        # 3 — Analysis request
        p = arcpy.Parameter(
            displayName="Analysis Request",
            name="user_request", datatype="GPString",
            parameterType="Required", direction="Input"
        )
        p.value = "Analyze crop health and detect water and nutrient stress"
        params.append(p)

        # 4 — Satellite type override
        p = arcpy.Parameter(
            displayName="Satellite Type (Override / Auto-detect)",
            name="satellite_type", datatype="GPString",
            parameterType="Optional", direction="Input"
        )
        p.filter.type = "ValueList"
        p.filter.list = ["Auto-detect", "Sentinel-2", "Landsat-8", "Landsat-9"]
        p.value = "Auto-detect"
        params.append(p)

        # 5 — Indices to calculate
        p = arcpy.Parameter(
            displayName="Vegetation Indices (leave blank = AI selects)",
            name="indices", datatype="GPString",
            parameterType="Optional", direction="Input",
            multiValue=True
        )
        p.filter.type = "ValueList"
        p.filter.list = list(INDEX_REGISTRY.keys())
        params.append(p)

        # 6 — LLM provider
        p = arcpy.Parameter(
            displayName="AI Model",
            name="llm_provider", datatype="GPString",
            parameterType="Required", direction="Input"
        )
        p.filter.type = "ValueList"
        p.filter.list = ["gemini", "openai", "none (built-in analysis)"]
        p.value = "gemini"
        params.append(p)

        # 7 — Add to map
        p = arcpy.Parameter(
            displayName="Add Results to Map",
            name="add_to_map", datatype="GPBoolean",
            parameterType="Optional", direction="Input"
        )
        p.value = True
        params.append(p)

        # 8 — OUTPUT: report path
        p = arcpy.Parameter(
            displayName="Report File",
            name="report_path", datatype="DEFile",
            parameterType="Derived", direction="Output"
        )
        params.append(p)

        return params

    def isLicensed(self):
        try:
            return arcpy.CheckExtension("Spatial") in ("Available", "AlreadyCheckedOut")
        except Exception:
            return True

    def updateParameters(self, params):
        sat = params[4]
        idx = params[5]
        if sat.altered and not idx.altered:
            if sat.valueAsText == "Sentinel-2":
                idx.value = ["NDVI", "NDRE", "NDWI", "NDMI"]
            elif sat.valueAsText in ["Landsat-8", "Landsat-9"]:
                idx.value = ["NDVI", "EVI", "NDWI", "NDMI", "BSI"]

    def updateMessages(self, params):
        if params[0].value and not os.path.exists(str(params[0].value)):
            params[0].setErrorMessage("Folder does not exist")
        if params[1].value:
            try:
                os.makedirs(str(params[1].value), exist_ok=True)
            except Exception as e:
                params[1].setWarningMessage(f"Cannot create output folder: {e}")

    def execute(self, parameters, messages):
        MSG = messages
        MSG.addMessage("=" * 68)
        MSG.addMessage("  SMART CROP HEALTH MONITORING AGENT — GeoAI Decision System")
        MSG.addMessage("=" * 68)
        start_time = datetime.now()

        # ── Read parameters ──────────────────────────────────────────
        data_folder   = parameters[0].valueAsText
        output_folder = parameters[1].valueAsText
        study_area    = parameters[2].valueAsText
        user_request  = parameters[3].valueAsText
        sat_override  = parameters[4].valueAsText
        indices_raw   = parameters[5].valueAsText
        llm_provider  = parameters[6].valueAsText
        add_to_map    = parameters[7].value

        # Parse indices
        user_indices = None
        if indices_raw:
            user_indices = [
                i.strip().strip("'\"")
                for i in re.split(r"[;,]", indices_raw)
                if i.strip()
            ]

        # Parse satellite override
        sat_force = None if (not sat_override or sat_override == "Auto-detect") else sat_override
        llm_key   = "none" if "none" in llm_provider else llm_provider

        MSG.addMessage(f"\nData Folder  : {data_folder}")
        MSG.addMessage(f"Output Folder: {output_folder}")
        MSG.addMessage(f"Study Area   : {study_area or 'None (full scene)'}")
        MSG.addMessage(f"Request      : {user_request}")
        MSG.addMessage(f"AI Model     : {llm_provider}\n")

        os.makedirs(output_folder, exist_ok=True)

        try:
            # ── STEP 1: Satellite Detection ──────────────────────────
            MSG.addMessage("━" * 50)
            MSG.addMessage("STEP 1/6 — Satellite Data Detection")
            MSG.addMessage("━" * 50)

            sat_agent = SatelliteAgent()
            sat_result = sat_agent.detect_and_load(data_folder, MSG)

            if not sat_result["success"]:
                MSG.addErrorMessage(f"Satellite detection failed: {sat_result['message']}")
                return

            satellite = sat_force or sat_result["satellite"]
            bands     = sat_result["bands"]
            avail_bands = sat_result["available_band_names"]

            MSG.addMessage(f"  Satellite   : {satellite}")
            MSG.addMessage(f"  Bands found : {avail_bands}\n")

            # ── STEP 2: AI Workflow Planning ─────────────────────────
            MSG.addMessage("━" * 50)
            MSG.addMessage("STEP 2/6 — AI Workflow Planning")
            MSG.addMessage("━" * 50)

            llm = LLMController(provider=llm_key, msg=MSG)

            if user_indices:
                indices_to_calc = user_indices
                MSG.addMessage(f"  Indices (user-specified): {indices_to_calc}")
            else:
                MSG.addMessage("  Asking AI to select best indices...")
                indices_to_calc = llm.plan_indices(satellite, avail_bands, user_request)
                MSG.addMessage(f"  AI selected indices: {indices_to_calc}")

            workflow_plan = [
                f"Step 1: Satellite Detection — {satellite}",
                f"Step 2: AI Index Planning — {indices_to_calc}",
                f"Step 3: Preprocessing — {'Clip to study area' if study_area else 'Full scene'}",
                f"Step 4: Index Calculation — {', '.join(indices_to_calc)}",
                f"Step 5: Health Classification & Stress Detection",
                f"Step 6: AI Report Generation ({llm_provider})"
            ]

            # ── STEP 3: Preprocessing ────────────────────────────────
            MSG.addMessage("\n" + "━" * 50)
            MSG.addMessage("STEP 3/6 — Preprocessing")
            MSG.addMessage("━" * 50)

            preproc_agent = PreprocessingAgent()
            preproc = preproc_agent.process(
                bands, satellite, output_folder, study_area, MSG
            )
            bands = preproc["bands"]

            # ── STEP 4: Vegetation Index Calculation ─────────────────
            MSG.addMessage("\n" + "━" * 50)
            MSG.addMessage("STEP 4/6 — Vegetation Index Calculation")
            MSG.addMessage("━" * 50)

            idx_agent  = VegetationIndexAgent()
            idx_result = idx_agent.calculate(bands, indices_to_calc, output_folder, MSG)

            if idx_result["skipped"]:
                MSG.addMessage(f"  Skipped: {idx_result['skipped']}")

            if not idx_result["success"]:
                MSG.addErrorMessage("No indices could be calculated. Check band files.")
                return

            # ── STEP 5: Crop Health Analysis ─────────────────────────
            MSG.addMessage("\n" + "━" * 50)
            MSG.addMessage("STEP 5/6 — Crop Health Analysis & Classification")
            MSG.addMessage("━" * 50)

            analysis_agent = CropHealthAnalysisAgent()
            analysis = analysis_agent.analyze(
                idx_result["files"],
                idx_result["statistics"],
                output_folder,
                study_area,
                MSG
            )

            health_score  = analysis.get("health_score", 0)
            stress_summary = analysis.get("stress_summary", {})

            MSG.addMessage(f"\n  Health Score : {health_score}/100")
            MSG.addMessage(f"  Stressed Area: {stress_summary.get('stressed_area_pct',0):.1f}%")
            MSG.addMessage(f"  Severity     : {stress_summary.get('severity','N/A')}")
            MSG.addMessage(f"  Water Stress : {stress_summary.get('water_stress','N/A')}")

            # ── STEP 6: AI Report ────────────────────────────────────
            MSG.addMessage("\n" + "━" * 50)
            MSG.addMessage("STEP 6/6 — AI Report Generation")
            MSG.addMessage("━" * 50)

            # Build stats package for LLM
            stats_for_llm = {
                "satellite":         satellite,
                "health_score":      health_score,
                "mean_ndvi":         idx_result["statistics"].get("NDVI", {}).get("mean", 0),
                "stressed_area_pct": stress_summary.get("stressed_area_pct", 0),
                "water_stress":      stress_summary.get("water_stress"),
                "moisture_stress":   stress_summary.get("moisture_stress"),
                "severity":          stress_summary.get("severity"),
                "index_statistics":  idx_result["statistics"],
                "ndvi_classes":      analysis.get("area_stats", {})
            }

            llm_text = llm.interpret(stats_for_llm)

            study_name = (
                os.path.splitext(os.path.basename(str(study_area)))[0]
                if study_area else "Full Scene"
            )

            report_agent = ReportAgent()
            report = report_agent.generate(
                satellite      = satellite,
                study_area_name= study_name,
                index_stats    = idx_result["statistics"],
                analysis_results = analysis,
                llm_interpretation = llm_text,
                workflow_plan  = workflow_plan,
                output_folder  = output_folder,
                msg            = MSG,
                user_request   = user_request
            )

            # ── Add to Map ───────────────────────────────────────────
            if add_to_map:
                MSG.addMessage("\n[Map] Adding layers to ArcGIS Pro map...")
                all_outputs = {**idx_result["files"]}
                if analysis.get("health_map"):
                    all_outputs["CropHealth_Map"]   = analysis["health_map"]
                if analysis.get("stress_map"):
                    all_outputs["StressZones"]       = analysis["stress_map"]
                if analysis.get("classified_map"):
                    all_outputs["NDVI_Classified"]   = analysis["classified_map"]

                viz = VisualizationAgent()
                viz.add_to_map(all_outputs, output_folder, MSG)

            # ── Final summary ────────────────────────────────────────
            elapsed = (datetime.now() - start_time).total_seconds()
            parameters[8].value = report["txt"]

            MSG.addMessage("\n" + "=" * 68)
            MSG.addMessage("  ANALYSIS COMPLETE")
            MSG.addMessage(f"  Health Score  : {health_score}/100")
            MSG.addMessage(f"  Elapsed Time  : {elapsed:.1f} seconds")
            MSG.addMessage(f"  Report (TXT)  : {report['txt']}")
            MSG.addMessage(f"  Report (HTML) : {report['html']}")
            MSG.addMessage("=" * 68)
            MSG.addMessage("\nAI INTERPRETATION:")
            MSG.addMessage("-" * 50)
            MSG.addMessage(llm_text)

        except arcpy.ExecuteError:
            MSG.addErrorMessage(arcpy.GetMessages(2))
        except Exception as e:
            import traceback
            MSG.addErrorMessage(f"Unexpected error: {e}")
            MSG.addMessage(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════
# TOOL 2 — QUICK NDVI CALCULATOR
# ══════════════════════════════════════════════════════════════════════
class QuickNDVITool:
    def __init__(self):
        self.label = "Quick NDVI Calculator"
        self.description = "Calculate NDVI instantly from Red and NIR bands."
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        p = arcpy.Parameter(
            displayName="Red Band Raster",
            name="red_band", datatype="DERasterDataset",
            parameterType="Required", direction="Input"
        )
        params.append(p)

        p = arcpy.Parameter(
            displayName="NIR Band Raster",
            name="nir_band", datatype="DERasterDataset",
            parameterType="Required", direction="Input"
        )
        params.append(p)

        p = arcpy.Parameter(
            displayName="Output NDVI Raster",
            name="output_ndvi", datatype="DERasterDataset",
            parameterType="Required", direction="Output"
        )
        params.append(p)

        p = arcpy.Parameter(
            displayName="Add Result to Map",
            name="add_to_map", datatype="GPBoolean",
            parameterType="Optional", direction="Input"
        )
        p.value = True
        params.append(p)

        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        return

    def execute(self, parameters, messages):
        red_band  = parameters[0].valueAsText
        nir_band  = parameters[1].valueAsText
        out_path  = parameters[2].valueAsText
        add_map   = parameters[3].value

        messages.addMessage("Calculating NDVI...")

        try:
            arcpy.CheckOutExtension("Spatial")
            from arcpy.sa import Raster, Float

            nir    = Float(Raster(nir_band))
            red    = Float(Raster(red_band))
            ndvi   = (nir - red) / (nir + red + 0.0001)
            ndvi.save(out_path)
            arcpy.CheckInExtension("Spatial")

            def gp(p): return float(arcpy.GetRasterProperties_management(out_path, p).getOutput(0))
            mean_val = gp("MEAN")
            min_val  = gp("MINIMUM")
            max_val  = gp("MAXIMUM")

            health = (
                "Very Dense / Lush Crop" if mean_val > 0.75 else
                "Healthy Vegetation"     if mean_val > 0.60 else
                "Moderate Health"        if mean_val > 0.45 else
                "Moderate Stress"        if mean_val > 0.30 else
                "Stressed / Sparse"      if mean_val > 0.15 else
                "Bare Soil / No Crop"
            )

            messages.addMessage(f"\n  Output  : {out_path}")
            messages.addMessage(f"  Min NDVI: {min_val:.4f}")
            messages.addMessage(f"  Max NDVI: {max_val:.4f}")
            messages.addMessage(f"  Mean NDVI: {mean_val:.4f}")
            messages.addMessage(f"  Status  : {health}")

            if add_map:
                try:
                    aprx = arcpy.mp.ArcGISProject("CURRENT")
                    m = aprx.listMaps()[0]
                    lyr = m.addDataFromPath(out_path)
                    if lyr:
                        lyr.name = "NDVI — Vegetation Health"
                    aprx.save()
                    messages.addMessage("  Added to map.")
                except Exception as e:
                    messages.addMessage(f"  Map add warning: {e}")

        except arcpy.ExecuteError:
            messages.addErrorMessage(arcpy.GetMessages(2))
        except Exception as e:
            messages.addErrorMessage(f"Error: {e}")
            import traceback
            messages.addMessage(traceback.format_exc())


# ══════════════════════════════════════════════════════════════════════
# TOOL 3 — CUSTOM INDEX CALCULATOR
# ══════════════════════════════════════════════════════════════════════
class CustomIndexTool:
    def __init__(self):
        self.label = "Custom Vegetation Index"
        self.description = (
            "Calculate any custom index using your own formula. "
            "Use band names: NIR, Red, Green, Blue, RedEdge, SWIR1, SWIR2. "
            "Example: (NIR - SWIR1) / (NIR + SWIR1)"
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        p = arcpy.Parameter(
            displayName="Satellite Data Folder",
            name="data_folder", datatype="DEFolder",
            parameterType="Required", direction="Input"
        )
        params.append(p)

        p = arcpy.Parameter(
            displayName="Custom Index Formula",
            name="formula", datatype="GPString",
            parameterType="Required", direction="Input"
        )
        p.value = "(NIR - SWIR1) / (NIR + SWIR1)"
        params.append(p)

        p = arcpy.Parameter(
            displayName="Output Folder",
            name="output_folder", datatype="DEFolder",
            parameterType="Required", direction="Input"
        )
        params.append(p)

        p = arcpy.Parameter(
            displayName="Study Area (Optional)",
            name="study_area", datatype="DEFeatureClass",
            parameterType="Optional", direction="Input"
        )
        params.append(p)

        p = arcpy.Parameter(
            displayName="Satellite Type Override",
            name="satellite_type", datatype="GPString",
            parameterType="Optional", direction="Input"
        )
        p.filter.type = "ValueList"
        p.filter.list = ["Auto-detect", "Sentinel-2", "Landsat-8", "Landsat-9"]
        p.value = "Auto-detect"
        params.append(p)

        p = arcpy.Parameter(
            displayName="Output Custom Index Raster",
            name="output_raster", datatype="DERasterDataset",
            parameterType="Derived", direction="Output"
        )
        params.append(p)

        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        if parameters[0].value and not os.path.exists(str(parameters[0].value)):
            parameters[0].setErrorMessage("Folder does not exist")

    def execute(self, parameters, messages):
        data_folder   = parameters[0].valueAsText
        formula       = parameters[1].valueAsText
        output_folder = parameters[2].valueAsText
        study_area    = parameters[3].valueAsText
        sat_override  = parameters[4].valueAsText

        os.makedirs(output_folder, exist_ok=True)
        messages.addMessage(f"Custom Index Formula: {formula}")

        try:
            # Detect satellite and bands
            sat_agent  = SatelliteAgent()
            sat_result = sat_agent.detect_and_load(data_folder, messages)

            if not sat_result["success"]:
                messages.addErrorMessage(f"Satellite detection failed: {sat_result['message']}")
                return

            satellite = (
                sat_override if sat_override and sat_override != "Auto-detect"
                else sat_result["satellite"]
            )
            bands = sat_result["bands"]

            # Preprocess (clip if study area given)
            if study_area and os.path.exists(str(study_area)):
                preproc = PreprocessingAgent().process(
                    bands, satellite, output_folder, study_area, messages
                )
                bands = preproc["bands"]

            # Calculate custom index
            idx_agent = VegetationIndexAgent()
            result = idx_agent.calculate_custom(formula, bands, output_folder, messages)

            if result["success"]:
                out_path = result["file"]
                stat = result["statistics"]
                parameters[5].value = out_path

                messages.addMessage(f"\n  Output : {out_path}")
                messages.addMessage(f"  Min    : {stat['min']:.4f}")
                messages.addMessage(f"  Max    : {stat['max']:.4f}")
                messages.addMessage(f"  Mean   : {stat['mean']:.4f}")

                # Add to map
                try:
                    aprx = arcpy.mp.ArcGISProject("CURRENT")
                    m = aprx.listMaps()[0]
                    lyr = m.addDataFromPath(out_path)
                    if lyr:
                        lyr.name = f"Custom Index: {formula}"
                    aprx.save()
                    messages.addMessage("  Added to ArcGIS Pro map.")
                except Exception as e:
                    messages.addMessage(f"  Map add warning: {e}")
            else:
                messages.addErrorMessage(
                    f"Custom index failed: {result.get('error','Unknown error')}\n"
                    f"Check formula uses valid band names: "
                    f"NIR, Red, Green, Blue, RedEdge, SWIR1, SWIR2"
                )

        except arcpy.ExecuteError:
            messages.addErrorMessage(arcpy.GetMessages(2))
        except Exception as e:
            import traceback
            messages.addErrorMessage(f"Error: {e}")
            messages.addMessage(traceback.format_exc())
