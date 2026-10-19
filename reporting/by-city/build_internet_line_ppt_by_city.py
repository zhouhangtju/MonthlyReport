#!/usr/bin/env python3
"""从地市及区县指标生成业务发展、专线自动和终端回收月报。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from database_results_by_city import build_data, month_bounds, normalize_city
from reporting.build_internet_line_ppt import replace_terminal_recovery_slides_from_template


REPORTING_DIR = HERE.parent
PROJECT_DIR = REPORTING_DIR.parent
DRAW_SCRIPT = HERE / "create_internet_line_ppt_by_city.js"
DEFAULT_TEMPLATE = REPORTING_DIR / "templates" / "通用模板.pptx"
OUTPUT_DIR = PROJECT_DIR / "outputs" / "city_monthly_report"
NODE_BIN = Path(shutil.which("node") or "node")
LOCAL_NODE_MODULES = REPORTING_DIR / "node_modules"
CODEX_NODE_MODULES = Path(
    "/Users/hzhou/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
)
WINDOWS_NODE_MODULES = Path(
    r"C:\Users\tanzhiyao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
)
NODE_MODULES = next(
    (path for path in (LOCAL_NODE_MODULES, CODEX_NODE_MODULES, WINDOWS_NODE_MODULES) if path.exists()),
    LOCAL_NODE_MODULES,
)


def _next_relationship_id(root):
    ids = []
    for relationship in root:
        match = re.fullmatch(r"rId(\d+)", relationship.attrib.get("Id", ""))
        if match:
            ids.append(int(match.group(1)))
    return f"rId{max(ids, default=0) + 1}"


def _point_slides_to_template_layout(xml_bytes, layout_name="slideLayout12.xml"):
    namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    ET.register_namespace("", namespace)
    root = ET.fromstring(xml_bytes)
    layout_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
    for relationship in root.findall(f"{{{namespace}}}Relationship"):
        if relationship.attrib.get("Type") == layout_type:
            relationship.set("Target", f"../slideLayouts/{layout_name}")
            return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.SubElement(root, f"{{{namespace}}}Relationship", {
        "Id": _next_relationship_id(root), "Type": layout_type,
        "Target": f"../slideLayouts/{layout_name}",
    })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _merge_template_content_types(output_xml, template_xml):
    namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("", namespace)
    output_root = ET.fromstring(output_xml)
    template_root = ET.fromstring(template_xml)
    defaults = {node.attrib.get("Extension") for node in output_root.findall(f"{{{namespace}}}Default")}
    overrides = {node.attrib.get("PartName") for node in output_root.findall(f"{{{namespace}}}Override")}
    prefixes = ("/ppt/slideMasters/", "/ppt/slideLayouts/", "/ppt/theme/")
    for node in template_root.findall(f"{{{namespace}}}Default"):
        if node.attrib.get("Extension") not in defaults:
            output_root.append(node)
            defaults.add(node.attrib.get("Extension"))
    for node in template_root.findall(f"{{{namespace}}}Override"):
        part_name = node.attrib.get("PartName", "")
        if part_name.startswith(prefixes) and part_name not in overrides:
            output_root.append(node)
            overrides.add(part_name)
    return ET.tostring(output_root, encoding="utf-8", xml_declaration=True)


def apply_template_master(pptx_path: Path, template_path: Path) -> None:
    prefixes = ("ppt/slideMasters/", "ppt/slideLayouts/", "ppt/theme/")
    temp_path = None
    try:
        with zipfile.ZipFile(pptx_path) as source, zipfile.ZipFile(template_path) as template:
            entries = {item.filename: source.read(item.filename) for item in source.infolist()}
            template_entries = {
                item.filename: template.read(item.filename) for item in template.infolist()
                if item.filename.startswith(prefixes) or item.filename == "ppt/media/image1.jpeg"
            }
            entries["[Content_Types].xml"] = _merge_template_content_types(
                entries["[Content_Types].xml"], template.read("[Content_Types].xml")
            )
        for name in list(entries):
            if name.startswith(prefixes):
                del entries[name]
            elif name.startswith("ppt/slides/_rels/") and name.endswith(".xml.rels"):
                entries[name] = _point_slides_to_template_layout(entries[name])
        entries.update(template_entries)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx", dir=pptx_path.parent) as handle:
            temp_path = Path(handle.name)
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            for name, content in entries.items():
                target.writestr(name, content)
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def month_argument(value: str) -> str:
    try:
        month_bounds(value)
        return value
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def verify_pptx(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        slides = [name for name in archive.namelist()
                  if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
    if len(slides) != 15:
        raise RuntimeError(f"地市版月报PPT页数应为15，实际为{len(slides)}")


def _format_count(value) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def apply_city_terminal_text(pptx_path: Path, terminal_data: dict) -> None:
    """在省级终端回收模板替换完成后，仅处理地市版文字口径。"""
    target_city = terminal_data["targetCity"]
    province_rate = f"{float(terminal_data['city']['rate']) * 100:.2f}%"
    target_rate = f"{float(terminal_data['targetCityRate']) * 100:.2f}%"
    province_completed = str(terminal_data["city"]["completedTotal"])
    target_completed = _format_count(terminal_data["targetCityCompletedTotal"])

    def update_runs(xml: str, exact: dict[str, str], fragments: dict[str, str]) -> str:
        def replace_match(match):
            value = match.group(1)
            if value in exact:
                value = exact[value]
            for old, new in fragments.items():
                value = value.replace(old, new)
            return f"<a:t>{escape(value)}</a:t>"
        return re.sub(r"<a:t>(.*?)</a:t>", replace_match, xml, flags=re.S)

    with zipfile.ZipFile(pptx_path, "r") as source_zip:
        entries = {info.filename: source_zip.read(info.filename) for info in source_zip.infolist()}
    slide12 = "ppt/slides/slide12.xml"
    slide13 = "ppt/slides/slide13.xml"
    if slide12 in entries:
        xml = entries[slide12].decode("utf-8")
        entries[slide12] = update_runs(
            xml,
            {f"{province_rate} ": f"{target_rate} "},
            {"全省终端回收率": f"{target_city}终端回收率"},
        ).encode("utf-8")
    if slide13 in entries:
        xml = entries[slide13].decode("utf-8")
        entries[slide13] = update_runs(
            xml,
            {province_completed: target_completed},
            {"全省终端": f"{target_city}终端"},
        ).encode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx", dir=pptx_path.parent) as tmp:
        temporary = Path(tmp.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for name, content in entries.items():
                target_zip.writestr(name, content)
        temporary.replace(pptx_path)
    finally:
        temporary.unlink(missing_ok=True)

def main() -> None:
    parser = argparse.ArgumentParser(description="生成指定地市业务发展、专线自动及终端回收情况PPTX")
    parser.add_argument("--month", required=True, type=month_argument, help="月报月份，YYYY-MM")
    parser.add_argument("--city", required=True, help="地市名称，例如杭州或杭州市")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 的MySQL配置")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--keep-json", action="store_true")
    args = parser.parse_args()

    city = normalize_city(args.city)
    year, number = map(int, args.month.split("-"))
    city_short = city.removesuffix("市")
    output = (
        args.output
        or OUTPUT_DIR / args.month / city_short / f"{city}业务发展情况_{year}年{number}月.pptx"
    ).resolve()
    template = args.template.expanduser().resolve()
    if not DRAW_SCRIPT.exists():
        raise FileNotFoundError(DRAW_SCRIPT)
    if not template.exists():
        raise FileNotFoundError(f"找不到PPT模板：{template}")
    if not NODE_MODULES.exists():
        raise FileNotFoundError(
            "找不到包含 pptxgenjs 的 Node 依赖目录；请安装项目PPT运行依赖，"
            f"或将依赖放到 {LOCAL_NODE_MODULES}"
        )

    data = build_data(args.database, args.month, city)
    if data["dataAudit"]["missing"]:
        fields = [item.get("metric_code", "terminal_recovery") + "/" + item["dimension_type"]
                  for item in data["dataAudit"]["missing"][:10]]
        raise RuntimeError("地市版PPT所需指标缺失：" + "，".join(fields))

    output.parent.mkdir(parents=True, exist_ok=True)
    data_json = output.with_suffix(".json")
    audit_json = output.with_suffix(".audit.json")
    data_json.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    audit_json.write_text(json.dumps(data["dataAudit"], ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    env = os.environ.copy()
    env["NODE_PATH"] = str(NODE_MODULES)
    env["PPT_TEMPLATE_MASTER"] = "1"
    subprocess.run([str(NODE_BIN), str(DRAW_SCRIPT), str(data_json), str(output)],
                   cwd=PROJECT_DIR, env=env, check=True)
    apply_template_master(output, template)
    replace_terminal_recovery_slides_from_template(output, data["terminalRecovery"], args.month)
    apply_city_terminal_text(output, data["terminalRecovery"])
    verify_pptx(output)
    if not args.keep_json:
        data_json.unlink(missing_ok=True)
    print(f"完成：{output}")


if __name__ == "__main__":
    main()
