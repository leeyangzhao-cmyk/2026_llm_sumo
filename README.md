# LLM + SUMO Scene Generator

This project generates runnable SUMO traffic simulation scenes from natural-language location descriptions.

The pipeline uses an LLM to parse scene requirements, downloads road data from OpenStreetMap through the Overpass API, converts the network with SUMO tools, generates random trips, and writes a SUMO configuration file that can be opened with `sumo-gui`.

The main research target is rapid urban road-network scenario generation for traffic simulation experiments.

## Project Layout

```text
2026_llm_sumo/
├── README.md
├── requirements.txt
├── config/
│   └── api_key.txt.example
└── src/
    ├── scene_generator.py
    ├── scene_generator_v2.py
    ├── network_toolgen.py
    ├── network_refiner.py
    ├── json_to_sumo.py
    └── test_api.py
```

Generated files are written to `outputs/`. This directory is ignored by Git because it can contain large regenerated SUMO networks, route files, logs, and simulation outputs.

The real API key file `config/api_key.txt` is also ignored and must not be committed.

## Scripts

### `scene_generator.py`

Recommended entry point when the user provides explicit latitude and longitude.

It parses the prompt, downloads OSM data, converts it to a SUMO network, generates random trips, creates optional POI markers, and writes a `.sumocfg`.

### `scene_generator_v2.py`

Advanced generator. It can ask the LLM to infer coordinates from a city or place name, and it can optionally filter elevated roads by OSM layer tags.

### `network_toolgen.py`

Uses the LLM to generate a small road-network processing toolchain, such as Overpass download scripts, CSV extraction scripts, and map viewers.

### `network_refiner.py`

Filters an existing SUMO `.net.xml` file by edge ID patterns. This is useful when isolating a subnetwork from a larger generated road network.

### `json_to_sumo.py`

Converts a simple JSON node/edge description into SUMO network input files, then calls `netconvert`.

### `test_api.py`

Checks that the Anthropic API key is available and that the selected model can be reached.

## Requirements

- Python 3.8 or newer
- SUMO 1.17 or newer
- `netconvert`, `sumo`, `sumo-gui`, and `randomTrips.py`
- Anthropic API key

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Set `SUMO_HOME` if SUMO is not already available on your `PATH`:

```powershell
$env:SUMO_HOME = "E:\SUMO"
```

## API Key

Use an environment variable when possible:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

Alternatively, copy the template and fill in your key locally:

```powershell
Copy-Item config\api_key.txt.example config\api_key.txt
```

`config/api_key.txt` is ignored by Git.

## Run

From the repository root:

```powershell
python src\test_api.py
python src\scene_generator.py
```

Example prompt format for `scene_generator.py`:

```text
Generate a SUMO scene near Zhuhai Mingzhu toll station, latitude 22.2150, longitude 113.5250, radius 1000 meters, medium traffic.
```

Open a generated scene:

```powershell
sumo-gui -c outputs\<scene_name>.sumocfg
```

## Notes

- Public Overpass servers may throttle or time out. The scripts include fallback server logic.
- LLM-inferred coordinates in `scene_generator_v2.py` are approximate. Use `scene_generator.py` with explicit latitude and longitude for precise infrastructure.
- Generated networks and simulation outputs are reproducible artifacts, so they are kept out of the repository.

## References

- SUMO: Lopez, P. A., et al. (2018). "Microscopic Traffic Simulation using SUMO." ITSC 2018.
- OpenStreetMap contributors, ODbL license: https://www.openstreetmap.org/copyright
- Anthropic Claude API: https://docs.anthropic.com
