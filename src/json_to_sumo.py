"""
JSON → SUMO Network Converter
Reads a JSON file describing nodes and roads, writes SUMO .nod.xml and .edg.xml,
runs netconvert, then generates random traffic with randomTrips.py.

Expected JSON format (see outputs/image_network_params.json for an example):
{
    "nodes": [
        {"id": "n1", "x": 0, "y": 0, "type": "priority"},
        ...
    ],
    "roads": [
        {"id": "e1", "from_node": "n1", "to_node": "n2", "num_lanes": 2},
        ...
    ]
}

Usage:
    python json_to_sumo.py [params.json]
    (defaults to ../outputs/image_network_params.json relative to this script)
"""

import json
import os
import sys
import subprocess


def _get_sumo_tools():
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        return os.path.join(sumo_home, "tools")
    for candidate in [r"C:\Program Files (x86)\Eclipse\Sumo", r"E:\SUMO"]:
        tools = os.path.join(candidate, "tools")
        if os.path.isdir(tools):
            return tools
    return os.path.join(r"C:\Program Files (x86)\Eclipse\Sumo", "tools")


def main(params_file=None):
    if params_file is None:
        params_file = os.path.join(
            os.path.dirname(__file__), '..', 'outputs', 'image_network_params.json'
        )

    if not os.path.exists(params_file):
        print(f"❌ 找不到参数文件: {params_file}")
        sys.exit(1)

    with open(params_file, 'r', encoding='utf-8') as f:
        params = json.load(f)

    print("读取到的路网参数：")
    print(json.dumps(params, indent=2, ensure_ascii=False))

    output_dir = os.path.dirname(os.path.abspath(params_file))

    # --- Generate nodes file ---
    nodes_file = os.path.join(output_dir, "image_network.nod.xml")

    nodes_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    nodes_xml += '<nodes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    nodes_xml += 'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/nodes_file.xsd">\n'
    for node in params['nodes']:
        nodes_xml += (
            f'    <node id="{node["id"]}" x="{node["x"]}" y="{node["y"]}" '
            f'type="{node["type"]}"/>\n'
        )
    nodes_xml += '</nodes>\n'

    with open(nodes_file, 'w', encoding='utf-8') as f:
        f.write(nodes_xml)

    print(f"\n✅ Nodes文件生成：{nodes_file}")

    # --- Generate edges file ---
    edges_file = os.path.join(output_dir, "image_network.edg.xml")

    edges_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    edges_xml += '<edges xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    edges_xml += 'xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/edges_file.xsd">\n'
    for road in params['roads']:
        edges_xml += (
            f'    <edge id="{road["id"]}" from="{road["from_node"]}" '
            f'to="{road["to_node"]}" numLanes="{road["num_lanes"]}" speed="13.89"/>\n'
        )
    edges_xml += '</edges>\n'

    with open(edges_file, 'w', encoding='utf-8') as f:
        f.write(edges_xml)

    print(f"✅ Edges文件生成：{edges_file}")

    # --- Run netconvert ---
    net_file = os.path.join(output_dir, "image_network.net.xml")

    print("\n正在生成SUMO路网...")
    cmd = [
        'netconvert',
        '--node-files', nodes_file,
        '--edge-files', edges_file,
        '--output-file', net_file
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if not os.path.exists(net_file):
        print("❌ 路网生成失败")
        print(result.stderr)
        sys.exit(1)

    print(f"✅ SUMO路网生成成功：{net_file}")

    # --- Generate traffic via randomTrips.py ---
    print("\n正在生成车辆...")

    route_file = os.path.join(output_dir, "image_network.rou.xml")
    sumo_tools = _get_sumo_tools()
    randomtrips_script = os.path.join(sumo_tools, "randomTrips.py")

    cmd2 = [
        sys.executable,
        randomtrips_script,
        '-n', net_file,
        '-o', route_file,
        '-e', '3600',
        '--period', '2'
    ]

    subprocess.run(cmd2, capture_output=True, text=True)

    if not os.path.exists(route_file):
        print("⚠️ 车辆生成失败，跳过配置文件")
        return

    print(f"✅ 车辆生成成功：{route_file}")

    # --- Create SUMO config ---
    config_file = os.path.join(output_dir, "image_network.sumocfg")

    config_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="{os.path.basename(net_file)}"/>
        <route-files value="{os.path.basename(route_file)}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
</configuration>"""

    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(config_content)

    print(f"✅ 配置文件生成成功：{config_file}")

    print("\n" + "=" * 50)
    print("✅ 从JSON参数生成的路网已完成！")
    print("=" * 50)
    print(f"\n运行仿真：sumo-gui -c {config_file}")


if __name__ == "__main__":
    params_file = sys.argv[1] if len(sys.argv) > 1 else None
    main(params_file)
