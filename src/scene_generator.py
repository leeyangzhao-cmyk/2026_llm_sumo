"""
LLM + SUMO Scene Generator
Parses a natural language scene description (with explicit lat/lon),
downloads OSM data, converts to SUMO network, and generates traffic.

Usage:
    python scene_generator.py
    (Enter location, lat/lon, radius, traffic level at the prompts.)
"""

import anthropic
import os
import subprocess
import json
import sys
import math
import xml.etree.ElementTree as ET


def _get_api_key():
    """Load API key from env var or config file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'api_key.txt')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    raise FileNotFoundError(
        "API key not found. Set ANTHROPIC_API_KEY env var or create config/api_key.txt"
    )


def _get_sumo_tools():
    """Locate SUMO tools directory from SUMO_HOME env var or common install paths."""
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        return os.path.join(sumo_home, "tools")
    for candidate in [r"C:\Program Files (x86)\Eclipse\Sumo", r"E:\SUMO"]:
        tools = os.path.join(candidate, "tools")
        if os.path.isdir(tools):
            return tools
    return os.path.join(r"C:\Program Files (x86)\Eclipse\Sumo", "tools")


class SceneGenerator:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.sumo_tools = _get_sumo_tools()
        self.output_dir = os.path.join(os.path.dirname(__file__), '..', 'outputs')

        # Store center coordinates for POI creation
        self.center_coords = None
        self.location_name = None

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def parse_user_input_simple(self, user_input):
        """Parse user description; expect explicit lat/lon in the text."""
        print("正在分析你的需求...")

        prompt = f"""你是一个交通仿真助手。用户想要生成一个SUMO交通仿真场景。

用户输入：{user_input}

请分析用户需求，提取以下关键信息，以JSON格式返回：
{{
    "city": "场景名称（用于命名文件，英文或拼音）",
    "location_name": "位置描述（中文）",
    "latitude": 纬度（数字，如果用户提供了就用用户的，如果没提供就设为null）,
    "longitude": 经度（数字，如果用户提供了就用用户的，如果没提供就设为null）,
    "radius": "半径（单位：米，数字）",
    "traffic_level": "交通密度（light/medium/heavy）"
}}

注意：
- 如果用户提供了经纬度坐标，直接使用用户的坐标
- 如果用户说"公里"或"千米"，转换成米
- 交通密度：轻度(light)约500车/小时，中度(medium)约2000车/小时，重度(heavy)约4000车/小时

只返回JSON，不要其他内容。"""

        message = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text.strip()

        if response_text.startswith("```json"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()

        try:
            params = json.loads(response_text)
            params['radius'] = int(params['radius'])

            print(f"\n✅ 理解你的需求：")
            print(f"   场景名称：{params['city']}")
            print(f"   位置：{params['location_name']}")
            if params.get('latitude') and params.get('longitude'):
                print(f"   经度：{params['longitude']}")
                print(f"   纬度：{params['latitude']}")
            else:
                print(f"   ⚠️ 未提供坐标，需要手动指定")
            print(f"   范围：半径{params['radius']}米")
            print(f"   交通：{params['traffic_level']}")

            return params
        except Exception as e:
            print(f"❌ 解析失败：{e}")
            return None

    def geo_to_cartesian(self, lat, lon, ref_lat, ref_lon):
        """Convert lat/lon to Cartesian offset (metres) relative to a reference point."""
        lat_offset = (lat - ref_lat) * 111000
        lon_offset = (lon - ref_lon) * 111000 * abs(math.cos(math.radians(ref_lat)))
        return (lon_offset, lat_offset)  # SUMO uses (x=east, y=north)

    def create_poi_file(self, net_file, city, location_name, center_lat, center_lon):
        """Create a SUMO POI file marking the target location."""
        print(f"\n[額外] 正在创建位置标注...")

        poi_file = os.path.join(self.output_dir, f"{city}.poi.xml")

        try:
            tree = ET.parse(net_file)
            root = tree.getroot()

            location_elem = root.find('location')
            if location_elem is not None:
                net_offset = location_elem.get('netOffset', '0.00,0.00')
                orig_boundary = location_elem.get('origBoundary')
                conv_boundary = location_elem.get('convBoundary')

                try:
                    offset_x, offset_y = map(float, net_offset.split(','))
                except Exception:
                    offset_x, offset_y = 0.0, 0.0

                if orig_boundary:
                    orig_parts = list(map(float, orig_boundary.split(',')))
                    ref_lon, ref_lat = orig_parts[0], orig_parts[1]
                    x, y = self.geo_to_cartesian(center_lat, center_lon, ref_lat, ref_lon)
                    x += offset_x
                    y += offset_y
                else:
                    if conv_boundary:
                        conv_parts = list(map(float, conv_boundary.split(',')))
                        x = (conv_parts[0] + conv_parts[2]) / 2
                        y = (conv_parts[1] + conv_parts[3]) / 2
                    else:
                        x, y = 0, 0
            else:
                x, y = 0, 0

            poi_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<additional xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/additional_file.xsd">
    <poi id="center_location" type="marker" color="1,0,0" layer="100" x="{x:.2f}" y="{y:.2f}">
        <param key="name" value="{location_name}"/>
        <param key="latitude" value="{center_lat:.6f}"/>
        <param key="longitude" value="{center_lon:.6f}"/>
    </poi>
    <poi id="north_500m" type="reference" color="0,0,1" layer="99" x="{x:.2f}" y="{y+500:.2f}">
        <param key="direction" value="北 500m"/>
    </poi>
    <poi id="south_500m" type="reference" color="0,0,1" layer="99" x="{x:.2f}" y="{y-500:.2f}">
        <param key="direction" value="南 500m"/>
    </poi>
    <poi id="east_500m" type="reference" color="0,0,1" layer="99" x="{x+500:.2f}" y="{y:.2f}">
        <param key="direction" value="东 500m"/>
    </poi>
    <poi id="west_500m" type="reference" color="0,0,1" layer="99" x="{x-500:.2f}" y="{y:.2f}">
        <param key="direction" value="西 500m"/>
    </poi>
</additional>"""

            with open(poi_file, 'w', encoding='utf-8') as f:
                f.write(poi_content)

            print(f"   ✅ POI标注创建成功")
            print(f"   📍 标注位置：{location_name}")
            return poi_file

        except Exception as e:
            print(f"   ❌ POI创建失败：{e}")
            return None

    def download_osm(self, city, lat, lon, radius):
        """Download OSM bounding-box data from Overpass API."""
        print(f"\n[1/5] 正在下载地图数据...")

        osm_file = os.path.join(self.output_dir, f"{city}.osm.xml")

        print(f"   中心坐标：纬度{lat}, 经度{lon}")
        print(f"   下载范围：半径{radius}米")

        self.center_coords = (lat, lon)

        lat_offset = (radius / 1000.0) / 111.0
        lon_offset = (radius / 1000.0) / (111.0 * abs(math.cos(math.radians(lat))))

        bbox = {
            'south': lat - lat_offset,
            'north': lat + lat_offset,
            'west': lon - lon_offset,
            'east': lon + lon_offset
        }

        import urllib.request

        overpass_servers = [
            "http://overpass-api.de/api/map",
            "http://overpass.kumi.systems/api/map",
        ]

        params_str = f"?bbox={bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"

        for idx, overpass_url in enumerate(overpass_servers):
            try:
                url = overpass_url + params_str
                print(f"   尝试服务器 {idx+1}: {overpass_url.split('/')[2]}")

                with urllib.request.urlopen(url, timeout=60) as response:
                    data = response.read()

                with open(osm_file, 'wb') as f:
                    f.write(data)

                if os.path.exists(osm_file) and os.path.getsize(osm_file) > 1000:
                    print(f"   ✅ 地图下载成功：{os.path.getsize(osm_file)} bytes")
                    return osm_file
                else:
                    print(f"   ⚠️ 下载的文件过小，尝试下一服务器")

            except Exception as e:
                print(f"   ⚠️ 服务器 {idx+1} 失败：{e}")
                continue

        print(f"   ❌ 所有服务器下载失败")
        return None

    def convert_to_network(self, osm_file, city):
        """Convert OSM XML to SUMO .net.xml via netconvert."""
        print(f"\n[2/5] 正在转换为SUMO路网...")

        net_file = os.path.join(self.output_dir, f"{city}.net.xml")

        try:
            cmd = [
                "netconvert",
                "--osm-files", osm_file,
                "--output-file", net_file,
                "--geometry.remove",
                "--ramps.guess",
                "--junctions.join",
                "--tls.guess-signals",
                "--tls.discard-simple",
                "--tls.join"
            ]

            print(f"   执行netconvert...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                    encoding='utf-8', errors='ignore')

            if os.path.exists(net_file):
                print(f"   ✅ 路网转换成功")
                return net_file
            else:
                print(f"   ❌ 转换失败")
                if result.stderr:
                    print(f"   错误信息：{result.stderr[:200]}")
                return None

        except Exception as e:
            print(f"   ❌ 转换出错：{e}")
            return None

    def generate_traffic(self, net_file, city, num_vehicles):
        """Generate random traffic routes via randomTrips.py."""
        print(f"\n[3/5] 正在生成{num_vehicles}辆车...")

        route_file = os.path.join(self.output_dir, f"{city}.rou.xml")

        try:
            randomtrips_script = os.path.join(self.sumo_tools, "randomTrips.py")

            cmd = [
                sys.executable,
                randomtrips_script,
                "-n", net_file,
                "-o", route_file,
                "-e", "3600",
                "--period", str(3600 / num_vehicles),
                "--fringe-factor", "10"
            ]

            print(f"   生成随机行程...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                    encoding='utf-8', errors='ignore')

            if os.path.exists(route_file):
                print(f"   ✅ 车辆生成成功")
                return route_file
            else:
                print(f"   ❌ 生成失败")
                return None

        except Exception as e:
            print(f"   ❌ 生成出错：{e}")
            return None

    def create_config(self, net_file, route_file, city, poi_file=None):
        """Create SUMO .sumocfg configuration file."""
        print(f"\n[4/5] 正在创建仿真配置...")

        config_file = os.path.join(self.output_dir, f"{city}.sumocfg")

        additional_files = ""
        if poi_file:
            additional_files = (
                f'\n        <additional-files value="{os.path.basename(poi_file)}"/>'
            )

        config_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="{os.path.basename(net_file)}"/>
        <route-files value="{os.path.basename(route_file)}"/>{additional_files}
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
</configuration>"""

        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            print(f"   ✅ 配置文件创建成功")
            return config_file
        except Exception as e:
            print(f"   ❌ 创建失败：{e}")
            return None

    def run_simulation(self, config_file, city, visualize=True):
        """Launch SUMO (with or without GUI)."""
        output_file = os.path.join(self.output_dir, f"{city}_output.xml")

        if visualize:
            print("\n正在启动SUMO可视化界面...")
            cmd = ["sumo-gui", "-c", config_file, "--tripinfo-output", output_file]
        else:
            print("\n正在运行后台仿真（无可视化）...")
            cmd = ["sumo", "-c", config_file, "--tripinfo-output", output_file, "--no-warnings", "true"]

        try:
            subprocess.run(cmd, capture_output=True, text=True)
            if os.path.exists(output_file):
                print(f"\n✅ 仿真完成！结果：{output_file}")
            return True
        except Exception as e:
            print(f"\n❌ 仿真运行出错：{e}")
            return False

    def generate_scene(self, params):
        """End-to-end: download OSM → SUMO network → traffic → config."""
        city = params['city']
        location_name = params['location_name']
        lat = params.get('latitude')
        lon = params.get('longitude')
        radius = params['radius']
        traffic = params['traffic_level']

        if not lat or not lon:
            print("\n❌ 错误：未提供经纬度坐标")
            print("💡 请在输入中包含经纬度，例如：")
            print("   '珠海明珠收费站，纬度22.2150，经度113.5250，半径2公里，轻度交通'")
            return False

        self.location_name = location_name

        traffic_map = {'light': 500, 'medium': 2000, 'heavy': 4000}
        num_vehicles = traffic_map.get(traffic, 2000)

        print(f"\n{'='*60}")
        print(f"开始生成场景：{location_name}")
        print(f"{'='*60}")

        osm_file = self.download_osm(city, lat, lon, radius)
        if not osm_file:
            return False

        net_file = self.convert_to_network(osm_file, city)
        if not net_file:
            return False

        poi_file = self.create_poi_file(net_file, city, location_name, lat, lon)

        route_file = self.generate_traffic(net_file, city, num_vehicles)
        if not route_file:
            return False

        config_file = self.create_config(net_file, route_file, city, poi_file)
        if not config_file:
            return False

        print(f"\n{'='*60}")
        print(f"✅ 场景生成完成！")
        print(f"{'='*60}")
        print(f"\n📁 生成的文件：")
        print(f"   路网文件: {net_file}")
        print(f"   路径文件: {route_file}")
        print(f"   配置文件: {config_file}")
        if poi_file:
            print(f"   标注文件: {poi_file}")

        run_sim = input("\n是否立即运行仿真？(y/n): ").strip().lower()
        if run_sim == 'y':
            visualize = input("是否需要可视化界面？(y/n): ").strip().lower()
            self.run_simulation(config_file, city, visualize=(visualize == 'y'))
        else:
            print(f"\n💡 稍后可以手动运行：")
            print(f"  可视化：sumo-gui -c {config_file}")
            print(f"  后台：  sumo -c {config_file}")

        return True


if __name__ == "__main__":
    api_key = _get_api_key()
    generator = SceneGenerator(api_key)

    print("=" * 60)
    print("LLM + SUMO 场景生成器（支持直接输入经纬度）")
    print("=" * 60)
    print("\n💡 使用提示：")
    print("   请在描述中包含经纬度坐标，例如：")
    print("   '珠海明珠收费站，纬度22.2150，经度113.5250，半径2公里，轻度交通'")
    print("   '北京天安门，经度116.4074，纬度39.9042，半径1000米，中度交通'")

    user_input = input("\n请描述你想要的仿真场景：\n> ")

    params = generator.parse_user_input_simple(user_input)
    if params:
        generator.generate_scene(params)
