"""
SUMO Network Refiner
Loads an existing SUMO .net.xml, lets Claude analyse the edge structure,
and filters it to a directional subset via keyword matching.

Usage:
    python network_refiner.py <path/to/network.net.xml>
"""

import os
import sys
import json
import xml.etree.ElementTree as ET
import anthropic


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


class NetworkRefiner:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.output_dir = os.path.join(os.path.dirname(__file__), '..', 'outputs', 'mingzhu_refined')

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def analyze_network(self, net_file):
        """Parse net.xml and collect basic edge statistics."""
        print("=" * 60)
        print("步骤1: 分析路网")
        print("=" * 60)

        try:
            tree = ET.parse(net_file)
            root = tree.getroot()

            edges = root.findall('.//edge')
            junctions = root.findall('.//junction')

            edge_info = []
            for edge in edges[:20]:
                edge_id = edge.get('id', '')
                edge_type = edge.get('type', '')
                from_node = edge.get('from', '')
                to_node = edge.get('to', '')
                lanes = edge.findall('.//lane')

                edge_info.append({
                    'id': edge_id,
                    'type': edge_type,
                    'from': from_node,
                    'to': to_node,
                    'lanes': len(lanes)
                })

            print(f"   路网规模:")
            print(f"   - 道路数: {len(edges)}")
            print(f"   - 交叉口数: {len(junctions)}")
            print(f"\n   前5条道路示例:")
            for info in edge_info[:5]:
                print(f"   - {info['id']}: {info['lanes']}车道, {info['from']}→{info['to']}")

            return {
                'total_edges': len(edges),
                'total_junctions': len(junctions),
                'sample_edges': edge_info,
                'tree': tree,
                'root': root
            }

        except Exception as e:
            print(f"   ❌ 分析失败: {e}")
            return None

    def ask_llm_for_filtering(self, network_info):
        """Ask Claude to suggest direction patterns based on edge IDs."""
        print("\n" + "=" * 60)
        print("步骤2: LLM智能识别道路方向")
        print("=" * 60)

        sample_text = "\n".join([
            f"- {e['id']}: {e['lanes']}车道, 从{e['from']}到{e['to']}"
            for e in network_info['sample_edges'][:10]
        ])

        prompt = f"""你是交通工程专家。分析这个SUMO路网，帮我识别：

路网信息：
- 总道路数: {network_info['total_edges']}
- 总交叉口数: {network_info['total_junctions']}

示例道路：
{sample_text}

任务：
用户想要"下行方向（西→东）的分流路段"，包括：
1. 主线（3车道+应急车道）
2. 东侧分流匝道

问题：
1. 从道路ID能看出方向吗？
2. 哪些道路ID可能是"上行"需要删除的？
3. 哪些道路ID可能是"下行"需要保留的？

返回JSON：
{{
    "direction_pattern": "道路ID中的方向规律",
    "eastbound_pattern": "上行道路的ID特征",
    "westbound_pattern": "下行道路的ID特征",
    "ramp_pattern": "匝道的ID特征",
    "suggestion": "筛选建议"
}}

只返回JSON。"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "").replace("```", "").strip()

            analysis = json.loads(response_text)

            print(f"   ✅ LLM分析结果:")
            print(f"   方向规律: {analysis.get('direction_pattern', 'N/A')}")
            print(f"   建议: {analysis.get('suggestion', 'N/A')}")

            return analysis

        except Exception as e:
            print(f"   ⚠️ LLM分析失败: {e}")
            return None

    def filter_by_user_choice(self, network_info):
        """Interactive filter selection."""
        print("\n" + "=" * 60)
        print("步骤3: 用户选择过滤规则")
        print("=" * 60)

        print("\n请选择过滤方式：")
        print("1. 按道路ID关键词过滤（推荐）")
        print("2. 全部保留（只看看）")

        choice = input("\n选择 [1/2]: ").strip()

        if choice == '1':
            return self._filter_by_keyword(network_info)
        else:
            print("   保留所有道路")
            return None

    def _filter_by_keyword(self, network_info):
        """Build a keyword-based filter rule interactively."""
        print("\n   方法: 关键词过滤")

        all_edges = [e['id'] for e in network_info['sample_edges']]
        print(f"\n   示例道路ID: {', '.join(all_edges[:10])}")

        print("\n   输入要【保留】的道路ID关键词（用空格分隔）")
        print("   或输入要【删除】的关键词前加'-'，例如: -eastbound -east")

        keywords = input("\n   关键词: ").strip().split()

        keep_keywords = [k for k in keywords if not k.startswith('-')]
        remove_keywords = [k[1:] for k in keywords if k.startswith('-')]

        print(f"\n   保留包含: {keep_keywords}")
        print(f"   删除包含: {remove_keywords}")

        return {
            'method': 'keyword',
            'keep': keep_keywords,
            'remove': remove_keywords
        }

    def apply_filter(self, network_info, filter_rule):
        """Apply a keyword filter to the network XML in-place."""
        print("\n" + "=" * 60)
        print("步骤4: 应用过滤规则")
        print("=" * 60)

        if not filter_rule:
            print("   跳过过滤")
            return network_info['root']

        root = network_info['root']
        edges = root.findall('.//edge')
        removed_count = 0

        if filter_rule['method'] == 'keyword':
            keep_kw = filter_rule['keep']
            remove_kw = filter_rule['remove']

            for edge in list(edges):
                edge_id = edge.get('id', '').lower()

                should_remove = False
                if remove_kw and any(kw.lower() in edge_id for kw in remove_kw):
                    should_remove = True
                if keep_kw and not any(kw.lower() in edge_id for kw in keep_kw):
                    should_remove = True

                if should_remove:
                    root.remove(edge)
                    removed_count += 1

        print(f"   ✅ 删除了 {removed_count} 条道路")
        print(f"   保留了 {len(root.findall('.//edge'))} 条道路")

        return root

    def save_refined_network(self, root, output_name="refined"):
        """Write the filtered network to file."""
        print("\n" + "=" * 60)
        print("步骤5: 保存优化路网")
        print("=" * 60)

        output_file = os.path.join(self.output_dir, f"{output_name}.net.xml")

        try:
            tree = ET.ElementTree(root)
            tree.write(output_file, encoding='utf-8', xml_declaration=True)
            print(f"   ✅ 保存成功: {output_file}")
            return output_file
        except Exception as e:
            print(f"   ❌ 保存失败: {e}")
            return None

    def refine_network(self, source_net_file):
        """Full pipeline: analyse → LLM hint → user filter → save."""
        print("\n" + "=" * 70)
        print(" " * 20 + "SUMO路网细化工具")
        print("=" * 70)
        print(f"\n输入文件: {source_net_file}\n")

        network_info = self.analyze_network(source_net_file)
        if not network_info:
            return False

        self.ask_llm_for_filtering(network_info)

        filter_rule = self.filter_by_user_choice(network_info)

        refined_root = self.apply_filter(network_info, filter_rule)

        output_file = self.save_refined_network(refined_root, output_name="refined_network")

        if output_file:
            print("\n" + "=" * 70)
            print("✅ 路网细化完成！")
            print("=" * 70)
            print(f"\n输出文件: {output_file}")
            print(f"查看命令: sumo-gui -n {output_file}")
            return True
        else:
            print("\n❌ 细化失败")
            return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python network_refiner.py <path/to/network.net.xml>")
        sys.exit(1)

    source_net = sys.argv[1]

    if not os.path.exists(source_net):
        print(f"❌ 找不到路网文件: {source_net}")
        sys.exit(1)

    api_key = _get_api_key()
    refiner = NetworkRefiner(api_key)
    refiner.refine_network(source_net)
