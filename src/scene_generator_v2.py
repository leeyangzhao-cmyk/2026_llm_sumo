"""
LLM + SUMO Scene Generator v2 — with OSM layer filtering
Parses natural language input (city name), asks Claude for coordinates,
downloads OSM data, optionally filters to elevated roads only (layer>=1),
then converts to SUMO network and generates traffic.

Usage:
    python scene_generator_v2.py
"""

import anthropic
import os
import subprocess
import json
import sys
import math
import xml.etree.ElementTree as ET


def _get_api_key():
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

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def parse_user_input(self, user_input):
        """Use Claude to extract city, location, radius, and traffic level."""
        print("正在分析你的需求...")

        prompt = f"""你是一个交通仿真助手。用户想要生成一个SUMO交通仿真场景。

用户输入：{user_input}

请分析用户需求，提取以下关键信息，以JSON格式返回：
{{
    "city": "城市名称（英文）",
    "location": "具体位置（如果有，用英文；如果没有就用城市中心）",
    "radius": "半径（单位：米，数字）",
    "traffic_level": "交通密度（light/medium/heavy）"
}}

注意：
- 如果用户说"公里"或"千米"，转换成米
- 如果用户说"英里"，1英里=1609米
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
            print(f"   城市：{params['city']}")
            if params.get('location'):
                print(f"   位置：{params['location']}")
            print(f"   范围：半径{params['radius']}米")
            print(f"   交通：{params['traffic_level']}")
            return params
        except Exception as e:
            print(f"❌ 解析失败：{e}")
            return None

    def get_city_coordinates(self, city, location):
        """Ask Claude for approximate lat/lon of the target location."""
        search_text = f"{location}, {city}" if location else city

        prompt = f"""请提供"{search_text}"的地理坐标（经纬度）。

只返回JSON格式：
{{
    "latitude": 纬度（数字）,
    "longitude": 经度（数字）
}}

只返回JSON，不要其他内容。"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "").replace("```", "").strip()

            coords = json.loads(response_text)
            return (coords['latitude'], coords['longitude'])

        except Exception as e:
            print(f"   获取坐标失败：{e}")
            return None

    def download_osm(self, city, location, radius):
        """Download OSM bounding-box data with dual-server fallback."""
        print(f"\n[1/5] 正在下载{city}的地图数据...")

        osm_file = os.path.join(self.output_dir, f"{city}.osm.xml")

        print(f"   正在获取{city}的地理坐标...")
        coords = self.get_city_coordinates(city, location)

        if not coords:
            print(f"   ⚠️ 无法获取坐标")
            return None

        lat, lon = coords
        print(f"   坐标：纬度{lat}, 经度{lon}")

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

        params = f"?bbox={bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"

        for idx, overpass_url in enumerate(overpass_servers):
            try:
                url = overpass_url + params
                print(f"   尝试服务器 {idx+1}: {overpass_url.split('/')[2]}")

                with urllib.request.urlopen(url, timeout=60) as response:
                    data = response.read()

                print(f"   下载完成，{len(data)} bytes")

                with open(osm_file, 'wb') as f:
                    f.write(data)

                tree = ET.parse(osm_file)
                root = tree.getroot()
                ways = root.findall('way')

                if len(ways) == 0:
                    print(f"   ⚠️ 无道路数据")
                    continue

                print(f"   ✅ 下载成功：{len(ways)} 条道路")
                return osm_file

            except Exception as e:
                print(f"   ⚠️ 服务器 {idx+1} 失败：{e}")
                continue

        print(f"   ❌ 所有服务器都失败")
        return None

    def filter_by_layer(self, osm_file, city):
        """
        Filter OSM ways to keep only layer>=1 (elevated/bridge) roads.
        Useful for isolating flyovers from at-grade roads in interchange areas.
        Returns path to filtered file, or None if no elevated roads found.
        """
        print(f"\n[2/5] 正在分离立交层级...")

        try:
            tree = ET.parse(osm_file)
            root = tree.getroot()

            total_ways = len(root.findall('way'))
            print(f"   原始道路：{total_ways} 条")

            # Collect layer statistics
            layer_count = {}
            for way in root.findall('way'):
                tags = {tag.get('k'): tag.get('v') for tag in way.findall('tag')}
                if not tags.get('highway'):
                    continue
                try:
                    layer_int = int(tags.get('layer', '0'))
                except ValueError:
                    layer_int = 0
                layer_count[layer_int] = layer_count.get(layer_int, 0) + 1

            print(f"\n   道路层级分布：")
            for layer in sorted(layer_count.keys()):
                print(f"     · Layer {layer}: {layer_count[layer]} 条")

            # Determine ways to keep
            ways_to_keep = set()
            for way in root.findall('way'):
                way_id = way.get('id')
                tags = {tag.get('k'): tag.get('v') for tag in way.findall('tag')}

                highway = tags.get('highway', '')
                if not highway:
                    continue

                try:
                    layer_int = int(tags.get('layer', '0'))
                except ValueError:
                    layer_int = 0

                bridge = tags.get('bridge', '')
                name = tags.get('name', '')

                keep = False
                if layer_int >= 1:
                    keep = True
                if bridge in ['yes', 'viaduct']:
                    keep = True
                if highway in ['motorway_link', 'trunk_link']:
                    keep = True
                if any(kw in name for kw in ['香海', 'Xianghai', '明珠', 'Mingzhu']):
                    if highway in ['motorway', 'trunk', 'motorway_link', 'trunk_link']:
                        keep = True

                if keep:
                    ways_to_keep.add(way_id)

            print(f"\n   保留高架道路：{len(ways_to_keep)} 条")

            if len(ways_to_keep) == 0:
                print(f"   ⚠️ 该区域没有高架道路（layer >= 1），不使用layer过滤")
                return None

            # Remove unwanted ways
            removed = 0
            for way in list(root.findall('way')):
                if way.get('id') not in ways_to_keep:
                    root.remove(way)
                    removed += 1

            print(f"   删除地面道路：{removed} 条")

            # Clean up unused nodes
            used_nodes = set()
            for way in root.findall('way'):
                for nd in way.findall('nd'):
                    used_nodes.add(nd.get('ref'))
            for node in list(root.findall('node')):
                if node.get('id') not in used_nodes:
                    root.remove(node)

            filtered_file = os.path.join(self.output_dir, f"{city}_elevated.osm.xml")
            tree.write(filtered_file, encoding='utf-8', xml_declaration=True)

            print(f"   ✅ 高架路网提取完成")
            return filtered_file

        except Exception as e:
            print(f"   ❌ 失败：{e}")
            return None

    def convert_to_network(self, osm_file, city):
        """Convert OSM XML to SUMO .net.xml via netconvert."""
        print(f"\n[3/5] 正在转换SUMO路网...")

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
                "--no-warnings", "true",
            ]

            print(f"   执行netconvert...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                encoding='utf-8',
                errors='ignore'
            )

            if os.path.exists(net_file):
                tree = ET.parse(net_file)
                root = tree.getroot()
                edges = root.findall('edge')
                print(f"   ✅ 转换成功：{len(edges)} 条道路")
                return net_file
            else:
                print(f"   ❌ 转换失败")
                return None

        except Exception as e:
            print(f"   ❌ 出错：{e}")
            return None

    def generate_traffic(self, net_file, city, num_vehicles):
        """Generate random traffic routes via randomTrips.py."""
        print(f"\n[4/5] 正在生成{num_vehicles}辆车...")

        route_file = os.path.join(self.output_dir, f"{city}.rou.xml")

        try:
            randomtrips_script = os.path.join(self.sumo_tools, "randomTrips.py")
            period = max(1, 3600 / num_vehicles)

            cmd = [
                sys.executable,
                randomtrips_script,
                "-n", net_file,
                "-o", route_file,
                "-e", "3600",
                "--period", str(period),
                "--fringe-factor", "10",
            ]

            print(f"   生成行程...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                errors='ignore'
            )

            if os.path.exists(route_file):
                tree = ET.parse(route_file)
                root = tree.getroot()
                vehicles = root.findall('.//vehicle')
                print(f"   ✅ 生成成功：{len(vehicles)} 辆车")
                return route_file
            else:
                print(f"   ❌ 生成失败")
                return None

        except Exception as e:
            print(f"   ❌ 出错：{e}")
            return None

    def create_config(self, net_file, route_file, city):
        """Create SUMO .sumocfg configuration file."""
        print(f"\n[5/5] 正在创建配置...")

        config_file = os.path.join(self.output_dir, f"{city}.sumocfg")

        config_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <input>
        <net-file value="{os.path.basename(net_file)}"/>
        <route-files value="{os.path.basename(route_file)}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
    <report>
        <no-warnings value="true"/>
    </report>
</configuration>"""

        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            print(f"   ✅ 配置完成")
            return config_file
        except Exception as e:
            print(f"   ❌ 失败：{e}")
            return None

    def run_simulation(self, config_file, city):
        """Launch SUMO-GUI."""
        print("\n启动SUMO-GUI...")
        output_file = os.path.join(self.output_dir, f"{city}_output.xml")
        cmd = ["sumo-gui", "-c", config_file, "--tripinfo-output", output_file]
        try:
            subprocess.run(cmd)
            print(f"\n✅ 仿真完成")
            return True
        except Exception as e:
            print(f"\n❌ 出错：{e}")
            return False

    def generate_scene(self, params, use_filter=True):
        """End-to-end scene generation with optional layer filtering."""
        city = params['city']
        location = params.get('location', '')
        radius = params['radius']
        traffic = params['traffic_level']

        traffic_map = {'light': 500, 'medium': 2000, 'heavy': 4000}
        num_vehicles = traffic_map.get(traffic, 500)

        print(f"\n{'='*60}")
        print(f"开始生成：{city}")
        print(f"{'='*60}")

        osm_file = self.download_osm(city, location, radius)
        if not osm_file:
            print("\n❌ 下载失败")
            return False

        if use_filter:
            filtered = self.filter_by_layer(osm_file, city)
            if filtered:
                osm_file = filtered
            else:
                print(f"   ⚠️ Layer过滤失败，使用原始路网")
        else:
            print(f"\n[2/5] 跳过过滤，使用全部道路")

        net_file = self.convert_to_network(osm_file, city)
        if not net_file:
            print("\n❌ 转换失败")
            return False

        route_file = self.generate_traffic(net_file, city, num_vehicles)
        if not route_file:
            print("\n❌ 车辆生成失败")
            return False

        config_file = self.create_config(net_file, route_file, city)
        if not config_file:
            print("\n❌ 配置失败")
            return False

        print(f"\n{'='*60}")
        print(f"✅ 场景生成完成")
        print(f"{'='*60}")

        run = input("\n是否运行仿真？(y/n): ").strip().lower()
        if run == 'y':
            self.run_simulation(config_file, city)
        else:
            print(f"\n手动运行：sumo-gui -c {config_file}")

        return True


if __name__ == "__main__":
    api_key = _get_api_key()
    generator = SceneGenerator(api_key)

    print("=" * 60)
    print("SUMO场景生成器 V2 — 支持高架道路过滤")
    print("=" * 60)

    user_input = input("\n请描述场景（城市 + 位置 + 半径 + 交通密度）：\n> ")

    if not user_input.strip():
        print("❌ 输入为空")
        sys.exit(1)

    params = generator.parse_user_input(user_input)

    if params:
        filter_choice = input("\n是否过滤道路（只保留高架/匝道 layer>=1）？(y/n): ").strip().lower()
        use_filter = (filter_choice == 'y')

        success = generator.generate_scene(params, use_filter=use_filter)
        if success:
            print("\n🎉 完成！")
        else:
            print("\n❌ 失败")
