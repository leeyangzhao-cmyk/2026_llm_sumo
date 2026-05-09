"""
LLM-based SUMO Network Tool Generator
Uses Claude to generate a full toolchain (bash script, Python extractors,
HTML visualizer, network refiner) for a given location's SUMO road network.

Workflow:
  1. generate_initial_network_script() — OSM download + netconvert bash script
  2. generate_edge_extractor()         — Python script: .net.xml → CSV
  3. generate_network_visualizer()     — Interactive HTML with Leaflet.js
  4. generate_network_refiner()        — Python script: extract sub-network by edge IDs
  5. generate_all_tools()              — Run 1-4 in sequence and write README

Usage:
    python network_toolgen.py
    (Edit LOCATION / BBOX / OUTPUT_DIR constants at the bottom first.)
"""

import anthropic
import os
import sys
import json
from pathlib import Path


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


class ClaudeSUMONetworkGenerator:
    """Use Claude API to generate SUMO network processing tools."""

    def __init__(self, api_key=None):
        if api_key is None:
            api_key = _get_api_key()
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-6"

    def generate_initial_network_script(self, location, bbox, output_dir="./output"):
        """Generate a bash script to download OSM data and run netconvert."""
        prompt = f"""
我需要生成一个完整的Bash脚本，用于获取SUMO路网。

**目标位置**：{location}
**边界框坐标**：{bbox}
**输出目录**：{output_dir}

请生成一个完整的Bash脚本，包含以下步骤：

1. 从OpenStreetMap下载数据（使用wget或curl从Overpass API）
2. 使用netconvert转换为SUMO路网文件
3. 必须保留的属性：
   - edge ID
   - 道路几何形状（shape）
   - 车道数（numLanes）
   - 道路层级（layer，用于区分高架/地面）
   - 道路类型（type）
   - 道路名称（name）
   - 连接关系

4. netconvert参数要求：
   - 保留所有道路层级信息
   - 正确处理高架和地面道路
   - 保留路口连接关系
   - 输出文件：initial_network.net.xml

请直接输出可执行的Bash脚本，不要有任何解释。脚本应该：
- 包含完整的错误处理
- 显示进度信息
- 创建必要的目录
- 检查SUMO是否安装

直接从#!/bin/bash开始输出。
"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        script_content = message.content[0].text

        if "```bash" in script_content:
            script_content = script_content.split("```bash")[1].split("```")[0].strip()
        elif "```" in script_content:
            script_content = script_content.split("```")[1].split("```")[0].strip()

        os.makedirs(output_dir, exist_ok=True)
        script_path = os.path.join(output_dir, "generate_network.sh")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        os.chmod(script_path, 0o755)

        print(f"✓ 路网生成脚本已保存到: {script_path}")
        print(f"  执行命令: bash {script_path}")

        return script_content

    def generate_edge_extractor(self, output_dir="./output"):
        """Generate a Python script to extract edge info from .net.xml to CSV."""
        prompt = """
请编写一个完整的Python脚本，从SUMO的.net.xml文件中提取道路信息并保存为CSV。

**要求**：

1. 输入：命令行参数指定.net.xml文件路径
2. 输出：同名的.csv文件

3. 提取以下信息：
   - edge_id：道路ID
   - from_junction：起始路口ID
   - to_junction：终止路口ID
   - street_name：道路名称
   - lanes：车道数
   - length：道路长度（米）
   - speed：限速（m/s）
   - shape：道路几何形状（WKT格式的LINESTRING）
   - layer：道路层级（用于区分高架/地面）
   - type：道路类型
   - priority：道路优先级

4. 代码要求：
   - 使用xml.etree.ElementTree解析
   - 处理缺失属性（使用默认值）
   - 输出CSV格式，UTF-8编码
   - 包含进度显示
   - 包含错误处理

请直接输出完整的Python代码，从import开始，不要有任何解释。
"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        code_content = message.content[0].text

        if "```python" in code_content:
            code_content = code_content.split("```python")[1].split("```")[0].strip()
        elif "```" in code_content:
            code_content = code_content.split("```")[1].split("```")[0].strip()

        os.makedirs(output_dir, exist_ok=True)
        script_path = os.path.join(output_dir, "extract_edges.py")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_content)

        print(f"✓ 道路信息提取脚本已保存到: {script_path}")
        print(f"  使用方法: python {script_path} <network.net.xml>")

        return code_content

    def generate_network_visualizer(self, output_dir="./output"):
        """Generate an interactive Leaflet HTML viewer for .net.xml files."""
        prompt = """
请创建一个完整的自包含HTML文件，用于交互式查看SUMO路网。

**功能要求**：

1. 输入：用户上传.net.xml文件
2. 使用Leaflet.js在地图上显示路网
3. 核心功能：
   - 显示所有道路，每条道路标注edge ID
   - 不同layer的道路用不同颜色（高架、地面等）
   - 点击道路显示详细信息（ID、类型、车道数、层级、长度等）
   - 搜索框：输入edge ID高亮显示对应道路
   - 筛选器：按道路类型、层级筛选
   - 导出功能：导出选中的edge ID列表为JSON

4. 技术要求：
   - 使用CDN加载Leaflet.js和其他库
   - 所有代码在一个HTML文件中
   - 使用OpenStreetMap作为底图
   - 响应式设计
   - 包含使用说明

5. 界面要求：
   - 左侧：文件上传、搜索、筛选面板
   - 右侧：地图显示
   - 底部：选中道路的详细信息
   - 工具栏：导出、清除选择等按钮

请直接输出完整的HTML代码，从<!DOCTYPE html>开始，不要有任何解释。
"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )

        html_content = message.content[0].text

        if "```html" in html_content:
            html_content = html_content.split("```html")[1].split("```")[0].strip()
        elif "```" in html_content:
            html_content = html_content.split("```")[1].split("```")[0].strip()

        os.makedirs(output_dir, exist_ok=True)
        html_path = os.path.join(output_dir, "network_viewer.html")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"✓ 路网可视化工具已保存到: {html_path}")
        print(f"  在浏览器中打开此文件即可使用")

        return html_content

    def generate_network_refiner(self, output_dir="./output"):
        """Generate a Python script to extract a sub-network by edge ID list."""
        prompt = """
请编写一个完整的Python脚本，从原始SUMO路网中提取指定的道路子集。

**功能**：

1. 输入参数：
   - 原始.net.xml文件路径
   - edge ID列表（JSON文件或命令行参数）
   - 输出.net.xml文件路径
   - 可选：是否扩展相邻道路（默认False）

2. 处理逻辑：
   - 读取原始路网
   - 提取指定的edge及其属性
   - 提取相关的junction节点
   - 提取edge之间的connection连接
   - 如果扩展模式：包含与指定edge直接相连的道路
   - 保留所有traffic light信号灯定义

3. 输出：
   - 新的.net.xml文件（只包含指定道路）
   - 生成统计报告（提取了多少edge、junction、connection）

4. 命令行接口：
   python refine_network.py <input.net.xml> <edge_ids.json> <output.net.xml> [--expand]

5. edge_ids.json格式：
   {"edge_ids": ["edge1", "edge2"], "description": "目标路段"}

6. 代码要求：
   - 使用xml.etree.ElementTree
   - 完整的错误处理
   - 保留XML格式和缩进
   - 进度显示
   - 详细的日志输出

请直接输出完整的Python代码，从import开始，不要有任何解释。
"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}]
        )

        code_content = message.content[0].text

        if "```python" in code_content:
            code_content = code_content.split("```python")[1].split("```")[0].strip()
        elif "```" in code_content:
            code_content = code_content.split("```")[1].split("```")[0].strip()

        os.makedirs(output_dir, exist_ok=True)
        script_path = os.path.join(output_dir, "refine_network.py")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_content)

        print(f"✓ 路网精炼脚本已保存到: {script_path}")
        print(f"  使用方法: python {script_path} <input.net.xml> <edge_ids.json> <output.net.xml>")

        return code_content

    def generate_all_tools(self, location, bbox, output_dir="./output"):
        """Run all four generators and write a README."""
        print("=" * 60)
        print("SUMO路网生成工具集 - 开始生成")
        print("=" * 60)
        print()

        files = {}

        print("[1/4] 生成路网获取脚本...")
        self.generate_initial_network_script(location, bbox, output_dir)
        files['network_script'] = os.path.join(output_dir, "generate_network.sh")
        print()

        print("[2/4] 生成道路信息提取脚本...")
        self.generate_edge_extractor(output_dir)
        files['extractor'] = os.path.join(output_dir, "extract_edges.py")
        print()

        print("[3/4] 生成交互式可视化工具...")
        self.generate_network_visualizer(output_dir)
        files['visualizer'] = os.path.join(output_dir, "network_viewer.html")
        print()

        print("[4/4] 生成路网精炼脚本...")
        self.generate_network_refiner(output_dir)
        files['refiner'] = os.path.join(output_dir, "refine_network.py")
        print()

        self._generate_usage_guide(location, bbox, output_dir, files)

        print("=" * 60)
        print("✓ 所有工具生成完成！")
        print("=" * 60)
        print(f"\n输出目录: {output_dir}")
        print(f"请查看 {os.path.join(output_dir, 'README.md')} 了解使用方法")

        return files

    def _generate_usage_guide(self, location, bbox, output_dir, files):
        guide = f"""# SUMO路网生成工具 - 使用指南

## 项目信息

- **目标位置**: {location}
- **边界框**: {bbox}
- **生成时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 工作流程

### 阶段1：获取初始路网
```bash
bash {files['network_script']}
# 下载OSM数据并生成 initial_network.net.xml
```

### 阶段2：分析道路信息
```bash
python {files['extractor']} {output_dir}/initial_network.net.xml
# 生成 initial_network.csv，包含所有道路的详细信息
```

### 阶段3：可视化并确认道路ID

1. 在浏览器中打开 `{files['visualizer']}`
2. 上传生成的 `initial_network.net.xml`
3. 对照航拍视频，在地图上找到对应的道路
4. 记录需要的道路的 edge ID
5. 使用导出功能保存 edge ID 列表为 JSON

### 阶段4：生成精确路网
```bash
# 创建 target_edges.json: {{"edge_ids": ["edge1", "edge2"], "description": "说明"}}
python {files['refiner']} {output_dir}/initial_network.net.xml target_edges.json {output_dir}/final_network.net.xml
# 添加 --expand 可包含相邻道路
```

## 注意事项

- **高架与地面分离**：CSV中的`layer`字段，layer > 0 为高架
- **坐标系统**：SUMO使用投影坐标（米），可视化工具自动转换为WGS84

---
生成工具版本：Claude API ({self.model}) + SUMO
"""
        readme_path = os.path.join(output_dir, "README.md")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(guide)
        print(f"✓ 使用指南已保存到: {readme_path}")


def main():
    API_KEY = _get_api_key()

    # Edit these constants for your target location
    LOCATION = "珠海香海高速明珠收费站"
    # [min_lon, min_lat, max_lon, max_lat]
    BBOX = [113.520, 22.200, 113.540, 22.220]
    OUTPUT_DIR = "./mingzhu_network"

    print(f"""
==================================================
SUMO路网生成工具
==================================================
目标位置: {LOCATION}
边界框: {BBOX}
输出目录: {OUTPUT_DIR}
==================================================
    """)

    generator = ClaudeSUMONetworkGenerator(api_key=API_KEY)

    try:
        files = generator.generate_all_tools(
            location=LOCATION,
            bbox=BBOX,
            output_dir=OUTPUT_DIR
        )

        print("\n✓ 完成！现在你可以：")
        print(f"  1. 执行: bash {files['network_script']}")
        print(f"  2. 然后查看: {files['visualizer']}")
        print(f"  3. 最后精炼路网，生成最终用于仿真的文件")

    except Exception as e:
        print(f"\n✗ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
