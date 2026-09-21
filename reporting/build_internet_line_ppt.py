import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reporting.database_results import build_data, month_bounds
from reporting.manual_results import DEFAULT_DIRECTORY, METRIC_SETS, AUTOMATION, WITHDRAWAL, QIKUAN, RETURN, REPEAT, COMBINED_REPEAT

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
DATA_SOURCE_DIR = BASE_DIR / "data_sources"
OUTPUT_DIR = BASE_DIR.parent / "outputs" / "monthly_report"
DEFAULT_INPUT = DATA_SOURCE_DIR / "专线产品情况_2026-07.xlsx"
DEFAULT_OUTPUT = OUTPUT_DIR / "互联网专线产品开通情况_2026年7月.pptx"
DRAW_SCRIPT = BASE_DIR / "create_internet_line_ppt.js"
DATA_JSON = OUTPUT_DIR / "internet_line_ppt_data.json"
DEFAULT_TEMPLATE = TEMPLATE_DIR / "通用模板.pptx"
TERMINAL_RECOVERY_TEMPLATE = TEMPLATE_DIR / "终端回收页模版.pptx"
TERMINAL_RECOVERY_RATE_WORKBOOK_PATTERN = "终端回收率汇总表_*.xlsx"
WITHDRAWAL_WORK_ORDER_PATTERN = "开通督办工单*.xls*"
WITHDRAWAL_WORK_ORDER_FALLBACK = Path(
    r"C:\Users\tanzhiyao\Documents\WeChat Files\wxid_uxqabeijxook22\FileStorage\Temp\Copy\开通督办工单2026-08-31 18_30_54.xls"
)
NODE_BIN = Path(shutil.which("node") or r"C:\Users\tanzhiyao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
NODE_MODULES = (
    BASE_DIR / "node_modules"
    if (BASE_DIR / "node_modules").exists()
    else Path(r"C:\Users\tanzhiyao\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules")
)

PRODUCTS = [
    "悦享专线动态IP版",
    "互联网专线套餐",
    "商务专线套餐（2020版）",
    "直播专线",
    "网吧专线套餐（2019版）",
    "高品质互联网专线",
]

PRODUCT_LABELS = {
    "悦享专线动态IP版": "悦享专线\n动态IP版",
    "互联网专线套餐": "互联网\n专线套餐",
    "商务专线套餐（2020版）": "商务专线套餐\n（2020版）",
    "直播专线": "直播专线",
    "网吧专线套餐（2019版）": "网吧专线套餐\n（2019版）",
    "高品质互联网专线": "高品质\n互联网专线",
}

CITY_ORDER = [
    "杭州市", "嘉兴市", "宁波市", "温州市", "金华市", "绍兴市",
    "湖州市", "台州市", "衢州市", "丽水市", "舟山市",
]

WITHDRAWAL_RESULT_COLUMNS = [
    "月份", "地市", "撤退单量", "竣工量", "工单总量", "撤退单率",
    "网络建设原因", "用户原因", "前台原因", "其他原因",
    "专线开通单竣工量", "7月受理竣工量", "6月之前受理竣工量",
]

COMPLAINT_FAULT_RESULT_COLUMNS = [
    "月份", "统计周期", "指标类型", "地市", "专线类率", "企宽或小微宽带率", "合计率",
]

SECTION_SLIDE_MAP = {
    "业务发展情况": [1, 2, 3, 4, 5, 6],
    "专线自动情况": [1, 2, 8, 9, 10],
    "终端回收情况": [1, 2, 12, 13],
    "业务支撑情况": [1, 2, 15, 16],
}


def chinese_month(month):
    period = pd.Period(month, freq="M")
    return f"{period.year}年{period.month}月"


def short_month(month):
    period = pd.Period(month, freq="M")
    return f"{period.year % 100:02d}.{period.month:02d}"


def month_argument(value):
    try:
        month_bounds(value)
        return pd.Period(value, freq="M")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"月份格式应为 YYYY-MM：{value}") from exc


def color_city_product_data_labels(pptx_path):
    """让第3、5、6页多系列地市图的数据标签颜色与各自柱体颜色一致。"""
    chart_specs = [
        {
            "markers": [
                "悦享专线动态IP版", "互联网专线套餐", "商务专线套餐（2020版）",
                "直播专线", "网吧专线套餐（2019版）", "高品质互联网专线",
            ],
            "colors": ["11B6D8", "E75B5B", "86C85B", "9B7BC4", "F28E2B", "3572B0"],
        },
        {
            "markers": ["地区内MPLSVPN套餐", "省内MPLSVPN套餐"],
            "colors": ["5B9BD5", "E75B5B"],
        },
        {
            "markers": [
                "光纤出租套餐", "地区内数字电路出租套餐", "地区间精品电路",
                "地区内SPN电路出租", "地区间数字电路出租套餐", "地区内精品电路",
            ],
            "colors": ["F28E2B", "E75B5B", "86C85B", "9B7BC4", "11B6D8", "3572B0"],
        },
    ]
    temp_path = None
    with zipfile.ZipFile(pptx_path, "r") as source:
        replacements = {}
        chart_files = [
            name for name in source.namelist()
            if name.startswith("ppt/charts/chart") and name.endswith(".xml")
        ]
        for spec in chart_specs:
            matched_name = None
            for name in chart_files:
                text = source.read(name).decode("utf-8")
                if all(marker in text for marker in spec["markers"]):
                    matched_name = name
                    break
            if matched_name is None:
                raise ValueError(f"未找到多系列地市柱状图：{spec['markers']}")

            chart_xml = source.read(matched_name).decode("utf-8")
            series_blocks = re.findall(r"<c:ser>.*?</c:ser>", chart_xml, flags=re.S)
            if len(series_blocks) != len(spec["colors"]):
                raise ValueError(f"图表系列数异常：{matched_name}，实际{len(series_blocks)}")
            for old_block, color in zip(series_blocks, spec["colors"]):
                new_block, count = re.subn(
                    r'(<c:dLbls>.*?<a:srgbClr val=")[0-9A-Fa-f]{6}("/>)',
                    rf'\g<1>{color}\2',
                    old_block,
                    count=1,
                    flags=re.S,
                )
                if count != 1:
                    raise ValueError(f"图表缺少可修改的数据标签颜色节点：{matched_name}")
                chart_xml = chart_xml.replace(old_block, new_block, 1)
            replacements[matched_name] = chart_xml.encode("utf-8")

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False, dir=pptx_path.parent) as tmp:
            temp_path = Path(tmp.name)
        with zipfile.ZipFile(temp_path, "w") as target:
            for item in source.infolist():
                payload = replacements.get(item.filename, source.read(item.filename))
                if item.filename.endswith(".xml"):
                    xml = payload.decode("utf-8")
                    xml = xml.replace('<a:ea typeface=""/>', '<a:ea typeface="Microsoft YaHei"/>')
                    xml = xml.replace('<a:cs typeface=""/>', '<a:cs typeface="Microsoft YaHei"/>')
                    xml = re.sub(
                        r'(<a:latin typeface="Microsoft YaHei"/>)(?!\s*<a:ea)',
                        r'\1<a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/>',
                        xml,
                    )
                    payload = xml.encode("utf-8")
                target.writestr(item, payload)

    try:
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def format_withdrawal_line_chart(pptx_path):
    """设置撤退单页折线系列为无填充、1磅线宽。"""
    temp_path = None
    line_sp_pr = (
        '<c:spPr><a:noFill/>'
        '<a:ln w="12700" cap="flat"><a:solidFill><a:srgbClr val="43B0CD"/></a:solidFill>'
        '<a:prstDash val="solid"/><a:round/></a:ln><a:effectLst/></c:spPr>'
    )
    marker_sp_pr = (
        '<c:spPr><a:noFill/>'
        '<a:ln w="12700" cap="flat"><a:solidFill><a:srgbClr val="43B0CD"/></a:solidFill>'
        '<a:prstDash val="solid"/><a:round/></a:ln><a:effectLst/></c:spPr>'
    )
    with zipfile.ZipFile(pptx_path, "r") as source:
        replacements = {}
        chart_files = [
            name for name in source.namelist()
            if name.startswith("ppt/charts/chart") and name.endswith(".xml")
        ]
        matched_name = None
        for name in chart_files:
            chart_xml = source.read(name).decode("utf-8")
            if "撤退单率" not in chart_xml or "<c:lineChart>" not in chart_xml:
                continue
            matched_name = name
            line_chart_match = re.search(r"<c:lineChart>.*?</c:lineChart>", chart_xml, flags=re.S)
            if not line_chart_match:
                break
            line_chart_xml = line_chart_match.group(0)
            line_chart_xml, line_count = re.subn(
                r"<c:spPr>.*?</c:spPr>(?=\s*<c:invertIfNegative)",
                line_sp_pr,
                line_chart_xml,
                count=1,
                flags=re.S,
            )
            line_chart_xml, marker_count = re.subn(
                r"(<c:marker>.*?<c:size[^>]*/>\s*)<c:spPr>.*?</c:spPr>",
                rf"\1{marker_sp_pr}",
                line_chart_xml,
                count=1,
                flags=re.S,
            )
            line_chart_xml, label_count = re.subn(
                r'<c:dLblPos val="[^"]+"/>',
                '<c:dLblPos val="t"/>',
                line_chart_xml,
                count=1,
                flags=re.S,
            )
            if line_count != 1 or marker_count != 1:
                raise ValueError(f"撤退单率折线图缺少可修改的线条或标记节点：{name}")
            if label_count != 1:
                raise ValueError(f"撤退单率折线图缺少可修改的数据标签位置节点：{name}")
            chart_xml = chart_xml.replace(line_chart_match.group(0), line_chart_xml, 1)
            legend_layout = (
                '<c:legend><c:legendPos val="t"/>'
                '<c:layout><c:manualLayout>'
                '<c:layoutTarget val="inner"/><c:xMode val="edge"/><c:yMode val="edge"/>'
                '<c:x val="0.58"/><c:y val="0.03"/><c:w val="0.36"/><c:h val="0.13"/>'
                '</c:manualLayout></c:layout>'
            )
            chart_xml, legend_count = re.subn(
                r'<c:legend><c:legendPos val="t"/>(?:<c:layout>.*?</c:layout>)?',
                legend_layout,
                chart_xml,
                count=1,
                flags=re.S,
            )
            if legend_count != 1:
                raise ValueError(f"撤退单率图表缺少可修改的图例节点：{name}")
            plot_layout = (
                '<c:plotArea><c:layout><c:manualLayout>'
                '<c:layoutTarget val="inner"/><c:xMode val="edge"/><c:yMode val="edge"/>'
                '<c:x val="0.005"/><c:y val="0.30"/><c:w val="0.985"/><c:h val="0.56"/>'
                '</c:manualLayout></c:layout>'
            )
            chart_xml, plot_count = re.subn(
                r'<c:plotArea><c:layout(?:>.*?</c:layout>|/>)',
                plot_layout,
                chart_xml,
                count=1,
                flags=re.S,
            )
            if plot_count != 1:
                raise ValueError(f"撤退单率图表缺少可修改的绘图区布局节点：{name}")
            replacements[name] = chart_xml.encode("utf-8")
            break
        if matched_name is None:
            raise ValueError("未找到撤退单率折线图")

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False, dir=pptx_path.parent) as tmp:
            temp_path = Path(tmp.name)
        with zipfile.ZipFile(temp_path, "w") as target:
            for item in source.infolist():
                payload = replacements.get(item.filename, source.read(item.filename))
                target.writestr(item, payload)

    try:
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def format_complaint_fault_charts(pptx_path):
    """统一重复投诉与新装报障页组合图折线样式，并调整表1图例位置。"""
    temp_path = None
    line_color = "9BBB59"
    line_sp_pr = (
        '<c:spPr><a:noFill/>'
        f'<a:ln w="19050" cap="flat"><a:solidFill><a:srgbClr val="{line_color}"/></a:solidFill>'
        '<a:prstDash val="solid"/><a:round/></a:ln><a:effectLst/></c:spPr>'
    )
    marker_sp_pr = (
        '<c:spPr><a:noFill/>'
        f'<a:ln w="19050" cap="flat"><a:solidFill><a:srgbClr val="{line_color}"/></a:solidFill>'
        '<a:prstDash val="solid"/><a:round/></a:ln><a:effectLst/></c:spPr>'
    )
    targets = {
        "重复投诉率": {
            "legend_layout": (
                '<c:legend><c:legendPos val="t"/>'
                '<c:layout><c:manualLayout>'
                '<c:layoutTarget val="inner"/><c:xMode val="edge"/><c:yMode val="edge"/>'
                '<c:x val="0.18"/><c:y val="0.11"/><c:w val="0.68"/><c:h val="0.08"/>'
                '</c:manualLayout></c:layout>'
            ),
            "plot_layout": (
                '<c:plotArea><c:layout><c:manualLayout>'
                '<c:layoutTarget val="inner"/><c:xMode val="edge"/><c:yMode val="edge"/>'
                '<c:x val="0.005"/><c:y val="0.25"/><c:w val="0.99"/><c:h val="0.62"/>'
                '</c:manualLayout></c:layout>'
            ),
        },
        "新装报障率": {
            "plot_layout": (
                '<c:plotArea><c:layout><c:manualLayout>'
                '<c:layoutTarget val="inner"/><c:xMode val="edge"/><c:yMode val="edge"/>'
                '<c:x val="0.005"/><c:y val="0.22"/><c:w val="0.99"/><c:h val="0.66"/>'
                '</c:manualLayout></c:layout>'
            ),
        },
    }

    with zipfile.ZipFile(pptx_path, "r") as source:
        replacements = {}
        chart_files = [
            name for name in source.namelist()
            if name.startswith("ppt/charts/chart") and name.endswith(".xml")
        ]
        matched_titles = set()
        for name in chart_files:
            chart_xml = source.read(name).decode("utf-8")
            target_title = next((title for title in targets if title in chart_xml), None)
            if target_title is None or "<c:lineChart>" not in chart_xml:
                continue

            line_chart_match = re.search(r"<c:lineChart>.*?</c:lineChart>", chart_xml, flags=re.S)
            if not line_chart_match:
                continue
            line_chart_xml = line_chart_match.group(0)
            line_chart_xml, line_count = re.subn(
                r"<c:spPr>.*?</c:spPr>(?=\s*<c:invertIfNegative)",
                line_sp_pr,
                line_chart_xml,
                count=1,
                flags=re.S,
            )
            line_chart_xml, marker_count = re.subn(
                r"(<c:marker>.*?<c:size[^>]*/>\s*)<c:spPr>.*?</c:spPr>",
                rf"\1{marker_sp_pr}",
                line_chart_xml,
                count=1,
                flags=re.S,
            )
            if line_count != 1 or marker_count != 1:
                raise ValueError(f"{target_title}折线图缺少可修改的线条或标记节点：{name}")

            chart_xml = chart_xml.replace(line_chart_match.group(0), line_chart_xml, 1)
            legend_layout = targets[target_title].get("legend_layout")
            if legend_layout:
                chart_xml, legend_count = re.subn(
                    r'<c:legend><c:legendPos val="[^"]+"/>(?:<c:layout>.*?</c:layout>)?',
                    legend_layout,
                    chart_xml,
                    count=1,
                    flags=re.S,
                )
                if legend_count != 1:
                    raise ValueError(f"{target_title}图表缺少可修改的图例节点：{name}")
            plot_layout = targets[target_title].get("plot_layout")
            if plot_layout:
                chart_xml, plot_count = re.subn(
                    r'<c:plotArea><c:layout(?:>.*?</c:layout>|/>)',
                    plot_layout,
                    chart_xml,
                    count=1,
                    flags=re.S,
                )
                if plot_count != 1:
                    raise ValueError(f"{target_title}图表缺少可修改的绘图区布局节点：{name}")
            replacements[name] = chart_xml.encode("utf-8")
            matched_titles.add(target_title)

        missing = set(targets) - matched_titles
        if missing:
            raise ValueError(f"未找到重复投诉与新装报障页图表：{sorted(missing)}")

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False, dir=pptx_path.parent) as tmp:
            temp_path = Path(tmp.name)
        with zipfile.ZipFile(temp_path, "w") as target:
            for item in source.infolist():
                payload = replacements.get(item.filename, source.read(item.filename))
                target.writestr(item, payload)

    try:
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _next_relationship_id(root):
    ids = []
    for rel in root:
        value = rel.attrib.get("Id", "")
        match = re.fullmatch(r"rId(\d+)", value)
        if match:
            ids.append(int(match.group(1)))
    return f"rId{max(ids, default=0) + 1}"


def _point_slides_to_template_layout(xml_bytes, layout_name="slideLayout12.xml"):
    ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ET.register_namespace("", ns)
    root = ET.fromstring(xml_bytes)
    layout_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
    for rel in root.findall(f"{{{ns}}}Relationship"):
        if rel.attrib.get("Type") == layout_type:
            rel.set("Target", f"../slideLayouts/{layout_name}")
            return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.SubElement(
        root,
        f"{{{ns}}}Relationship",
        {
            "Id": _next_relationship_id(root),
            "Type": layout_type,
            "Target": f"../slideLayouts/{layout_name}",
        },
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _merge_template_content_types(output_xml, template_xml):
    ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("", ns)
    output_root = ET.fromstring(output_xml)
    template_root = ET.fromstring(template_xml)
    existing_defaults = {node.attrib.get("Extension") for node in output_root.findall(f"{{{ns}}}Default")}
    existing_overrides = {node.attrib.get("PartName") for node in output_root.findall(f"{{{ns}}}Override")}
    template_prefixes = (
        "/ppt/slideMasters/",
        "/ppt/slideLayouts/",
        "/ppt/theme/",
    )
    for node in template_root.findall(f"{{{ns}}}Default"):
        if node.attrib.get("Extension") not in existing_defaults:
            output_root.append(node)
            existing_defaults.add(node.attrib.get("Extension"))
    for node in template_root.findall(f"{{{ns}}}Override"):
        part_name = node.attrib.get("PartName", "")
        if part_name.startswith(template_prefixes) and part_name not in existing_overrides:
            output_root.append(node)
            existing_overrides.add(part_name)
    return ET.tostring(output_root, encoding="utf-8", xml_declaration=True)


def _rels_path_for_part(part_name):
    path = Path(part_name)
    return str(path.parent / "_rels" / f"{path.name}.rels").replace("\\", "/")


def _resolve_relationship_target(source_part, target):
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    source_dir = Path(source_part).parent
    return posixpath.normpath((source_dir / target).as_posix())


def _relative_relationship_target(source_part, target_part):
    source_dir = Path(source_part).parent
    return Path(os.path.relpath(target_part, source_dir)).as_posix()


def _terminal_template_part_name(part_name):
    path = Path(part_name)
    return str(path.parent / f"terminal_{path.name}").replace("\\", "/")


def _copy_content_type_overrides(output_xml, template_xml, part_mapping):
    ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("", ns)
    output_root = ET.fromstring(output_xml)
    template_root = ET.fromstring(template_xml)
    output_overrides = {node.attrib.get("PartName") for node in output_root.findall(f"{{{ns}}}Override")}
    template_overrides = {
        node.attrib.get("PartName"): node.attrib.get("ContentType")
        for node in template_root.findall(f"{{{ns}}}Override")
    }
    for old_part, new_part in part_mapping.items():
        new_part_name = f"/{new_part}"
        if new_part_name in output_overrides:
            continue
        content_type = template_overrides.get(f"/{old_part}")
        if content_type is None:
            continue
        ET.SubElement(output_root, f"{{{ns}}}Override", {"PartName": new_part_name, "ContentType": content_type})
        output_overrides.add(new_part_name)
    return ET.tostring(output_root, encoding="utf-8", xml_declaration=True)


def _register_terminal_slide_master(entries):
    rels_name = "ppt/_rels/presentation.xml.rels"
    presentation_name = "ppt/presentation.xml"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    pres_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    rel_doc_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ET.register_namespace("", rel_ns)
    ET.register_namespace("p", pres_ns)
    ET.register_namespace("r", rel_doc_ns)

    rel_root = ET.fromstring(entries[rels_name])
    master_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
    terminal_target = "slideMasters/terminal_slideMaster1.xml"
    terminal_rel_id = None
    for rel in rel_root.findall(f"{{{rel_ns}}}Relationship"):
        if rel.attrib.get("Type") == master_type and rel.attrib.get("Target") == terminal_target:
            terminal_rel_id = rel.attrib.get("Id")
            break
    if terminal_rel_id is None:
        terminal_rel_id = _next_relationship_id(rel_root)
        ET.SubElement(
            rel_root,
            f"{{{rel_ns}}}Relationship",
            {"Id": terminal_rel_id, "Type": master_type, "Target": terminal_target},
        )
    entries[rels_name] = ET.tostring(rel_root, encoding="utf-8", xml_declaration=True)

    pres_root = ET.fromstring(entries[presentation_name])
    master_list = pres_root.find(f"{{{pres_ns}}}sldMasterIdLst")
    if master_list is None:
        master_list = ET.Element(f"{{{pres_ns}}}sldMasterIdLst")
        pres_root.insert(0, master_list)
    for node in master_list.findall(f"{{{pres_ns}}}sldMasterId"):
        if node.attrib.get(f"{{{rel_doc_ns}}}id") == terminal_rel_id:
            break
    else:
        existing_ids = [
            int(node.attrib.get("id"))
            for node in master_list.findall(f"{{{pres_ns}}}sldMasterId")
            if str(node.attrib.get("id", "")).isdigit()
        ]
        ET.SubElement(
            master_list,
            f"{{{pres_ns}}}sldMasterId",
            {"id": str(max(existing_ids, default=2147483647) + 1), f"{{{rel_doc_ns}}}id": terminal_rel_id},
        )
    entries[presentation_name] = ET.tostring(pres_root, encoding="utf-8", xml_declaration=True)


def _rewrite_relationships(xml_bytes, source_part, mapped_source_part, part_mapping):
    ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ET.register_namespace("", ns)
    root = ET.fromstring(xml_bytes)
    for rel in root.findall(f"{{{ns}}}Relationship"):
        if rel.attrib.get("TargetMode") == "External":
            continue
        target = rel.attrib.get("Target", "")
        resolved = _resolve_relationship_target(source_part, target)
        if resolved not in part_mapping:
            continue
        rel.set("Target", _relative_relationship_target(mapped_source_part, part_mapping[resolved]))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _collect_related_template_parts(template_zip, seed_mapping):
    mapping = dict(seed_mapping)
    queue = list(seed_mapping)
    visited = set()
    while queue:
        old_part = queue.pop(0)
        if old_part in visited:
            continue
        visited.add(old_part)
        rels_path = _rels_path_for_part(old_part)
        if rels_path not in template_zip.namelist():
            continue
        rels_root = ET.fromstring(template_zip.read(rels_path))
        ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for rel in rels_root.findall(f"{{{ns}}}Relationship"):
            if rel.attrib.get("TargetMode") == "External":
                continue
            target = rel.attrib.get("Target", "")
            resolved = _resolve_relationship_target(old_part, target)
            if resolved not in template_zip.namelist():
                continue
            if resolved not in mapping:
                mapping[resolved] = _terminal_template_part_name(resolved)
                queue.append(resolved)
    return mapping


def _chart_str_cache(values):
    points = "".join(
        f'<c:pt idx="{idx}"><c:v>{escape(str(value))}</c:v></c:pt>'
        for idx, value in enumerate(values)
    )
    return f'<c:strCache><c:ptCount val="{len(values)}"/>{points}</c:strCache>'


def _chart_num_cache(values, format_code="General"):
    points = "".join(
        f'<c:pt idx="{idx}"><c:v>{float(value):.12g}</c:v></c:pt>'
        for idx, value in enumerate(values)
    )
    return f'<c:numCache><c:formatCode>{format_code}</c:formatCode><c:ptCount val="{len(values)}"/>{points}</c:numCache>'


def _replace_first_str_cache(xml, values):
    replacement = _chart_str_cache(values)
    xml, count = re.subn(r"<c:strCache>.*?</c:strCache>", replacement, xml, count=1, flags=re.S)
    if count == 0:
        raise ValueError("图表系列缺少可替换的字符串缓存")
    return xml


def _replace_category_cache(ser_xml, labels):
    category_match = re.search(r"<c:cat>.*?</c:cat>", ser_xml, flags=re.S)
    if not category_match:
        raise ValueError("图表系列缺少分类轴缓存")
    category_xml = category_match.group(0)
    category_cache = _chart_str_cache(labels)
    category_xml, count = re.subn(
        r"<c:strCache>.*?</c:strCache>|<c:multiLvlStrCache>.*?</c:multiLvlStrCache>",
        category_cache,
        category_xml,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise ValueError("图表系列缺少可替换的分类缓存")
    return ser_xml.replace(category_match.group(0), category_xml, 1)


def _replace_value_cache(ser_xml, values, format_code="General"):
    value_match = re.search(r"<c:val>.*?</c:val>", ser_xml, flags=re.S)
    if not value_match:
        raise ValueError("图表系列缺少数值缓存")
    value_xml = value_match.group(0)
    value_xml, count = re.subn(
        r"<c:numCache>.*?</c:numCache>",
        _chart_num_cache(values, format_code),
        value_xml,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise ValueError("图表系列缺少可替换的数值缓存")
    return ser_xml.replace(value_match.group(0), value_xml, 1)


def _replace_formula_refs(ser_xml, series_index, point_count):
    refs = iter([
        f"'TerminalRecovery'!$A${series_index + 1}",
        f"'TerminalRecovery'!$B$1:$B${point_count}",
        f"'TerminalRecovery'!$C$1:$C${point_count}",
    ])

    def replace_ref(_match):
        return f"<c:f>{next(refs)}</c:f>"

    return re.sub(r"<c:f>.*?</c:f>", replace_ref, ser_xml, count=3, flags=re.S)


def _replace_chart_series_caches(chart_xml, series_specs):
    series_matches = list(re.finditer(r"<c:ser>.*?</c:ser>", chart_xml, flags=re.S))
    if len(series_matches) != len(series_specs):
        raise ValueError(f"图表系列数量不匹配：模板{len(series_matches)}个，结果数据{len(series_specs)}个")
    pieces = []
    last_end = 0
    for match, spec in zip(series_matches, series_specs):
        ser_xml = match.group(0)
        ser_xml = _replace_first_str_cache(ser_xml, [spec["name"]])
        ser_xml = _replace_category_cache(ser_xml, spec["labels"])
        ser_xml = _replace_value_cache(ser_xml, spec["values"], spec.get("format_code", "General"))
        ser_xml = _replace_formula_refs(ser_xml, spec.get("series_index", 0), len(spec["labels"]))
        pieces.append(chart_xml[last_end:match.start()])
        pieces.append(ser_xml)
        last_end = match.end()
    pieces.append(chart_xml[last_end:])
    return "".join(pieces)


def _update_terminal_chart_caches(entries, terminal_data):
    def series_by_name(group, order):
        lookup = {item["name"]: item for item in terminal_data[group]["series"]}
        return [
            {"name": name, "labels": terminal_data[group]["labels"], "values": lookup[name]["values"], "series_index": idx}
            for idx, name in enumerate(order)
        ]

    chart_specs = {
        "ppt/charts/terminal_chart1.xml": [
            {"name": "应拆回设备数", "labels": terminal_data["city"]["labels"], "values": terminal_data["city"]["expected"], "series_index": 0},
            {"name": "已拆回设备数量", "labels": terminal_data["city"]["labels"], "values": terminal_data["city"]["completed"], "series_index": 1},
            {"name": "终端回收率", "labels": terminal_data["city"]["labels"], "values": terminal_data["city"]["rates"], "format_code": "0.00%", "series_index": 2},
        ],
        "ppt/charts/terminal_chart2.xml": [
            {"name": "应拆回设备数", "labels": terminal_data["topInstaller"]["labels"], "values": terminal_data["topInstaller"]["expected"], "series_index": 0},
            {"name": "已拆回设备数量", "labels": terminal_data["topInstaller"]["labels"], "values": terminal_data["topInstaller"]["completed"], "series_index": 1},
            {"name": "终端回收率", "labels": terminal_data["topInstaller"]["labels"], "values": terminal_data["topInstaller"]["rates"], "format_code": "0.00%", "series_index": 2},
        ],
        "ppt/charts/terminal_chart3.xml": series_by_name("business", ["ONU", "摄像头", "FTTO", "WIFI路由器", "专线卫士"]),
        "ppt/charts/terminal_chart4.xml": series_by_name("cityDevices", ["ONU", "FTTO", "摄像头", "WIFI路由器", "专线卫士"]),
        "ppt/charts/terminal_chart5.xml": series_by_name("installerDevices", ["ONU", "摄像头", "FTTO", "WIFI路由器", "专线卫士"]),
    }
    for chart_name, specs in chart_specs.items():
        if chart_name not in entries:
            raise ValueError(f"终端回收模板缺少图表：{chart_name}")
        chart_xml = entries[chart_name].decode("utf-8")
        entries[chart_name] = _replace_chart_series_caches(chart_xml, specs).encode("utf-8")


def _format_percent(value):
    return f"{float(value) * 100:.2f}%"


def _replace_text_runs(xml, replacements):
    def replace_match(match):
        value = match.group(1)
        return f"<a:t>{escape(str(replacements.get(value, value)))}</a:t>"

    return re.sub(r"<a:t>(.*?)</a:t>", replace_match, xml, flags=re.S)


def _update_terminal_slide_text(entries, terminal_data, display_month):
    month_text = str(pd.Period(display_month, freq="M").month)
    city = terminal_data["city"]
    top = terminal_data["topInstaller"]
    top_devices = terminal_data["topDevices"]
    while len(top_devices) < 3:
        top_devices.append({"name": "", "value": 0})

    slide12_replacements = {
        "      7": f"      {month_text}",
        "7": month_text,
        "17518": str(city["expectedTotal"]),
        "16275": str(city["completedTotal"]),
        "92.90%": _format_percent(city["rate"]),
        "92.90% ": f"{_format_percent(city['rate'])} ",
        "台州、舟山、金华": "、".join(city["bottomRankNames"]),
        " 东阳、莲都、洞头": f" {'、'.join(top['bottomRankNames'])}",
    }
    slide13_replacements = {
        "7": month_text,
        "16275": str(city["completedTotal"]),
        "ONU 6572 ": f"{top_devices[0]['name']} {top_devices[0]['value']} ",
        "FTTO": top_devices[1]["name"],
        " 3114 ": f" {top_devices[1]['value']} ",
        "摄像头": top_devices[2]["name"],
        " 2099 ": f" {top_devices[2]['value']} ",
    }

    for slide_name, replacements in {
        "ppt/slides/slide12.xml": slide12_replacements,
        "ppt/slides/slide13.xml": slide13_replacements,
    }.items():
        if slide_name in entries:
            entries[slide_name] = _replace_text_runs(
                entries[slide_name].decode("utf-8"),
                replacements,
            ).encode("utf-8")


def replace_terminal_recovery_slides_from_template(pptx_path, terminal_data, display_month, template_path=TERMINAL_RECOVERY_TEMPLATE):
    """用终端回收页模板内容页替换第12-13页，实现版式一比一复刻。"""
    if not template_path.exists():
        return
    temp_path = None
    seed_mapping = {
        "ppt/slides/slide2.xml": "ppt/slides/slide12.xml",
        "ppt/slides/slide3.xml": "ppt/slides/slide13.xml",
    }
    with zipfile.ZipFile(pptx_path, "r") as source_zip, zipfile.ZipFile(template_path, "r") as template_zip:
        entries = {info.filename: source_zip.read(info.filename) for info in source_zip.infolist()}
        part_mapping = _collect_related_template_parts(template_zip, seed_mapping)

        for old_part, new_part in part_mapping.items():
            entries[new_part] = template_zip.read(old_part)
            old_rels = _rels_path_for_part(old_part)
            if old_rels in template_zip.namelist():
                new_rels = _rels_path_for_part(new_part)
                entries[new_rels] = _rewrite_relationships(
                    template_zip.read(old_rels),
                    old_part,
                    new_part,
                    part_mapping,
                )

        entries["[Content_Types].xml"] = _copy_content_type_overrides(
            entries["[Content_Types].xml"],
            template_zip.read("[Content_Types].xml"),
            part_mapping,
        )
        _register_terminal_slide_master(entries)
        _update_terminal_chart_caches(entries, terminal_data)
        _update_terminal_slide_text(entries, terminal_data, display_month)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx", dir=pptx_path.parent) as tmp:
            temp_path = Path(tmp.name)
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for name, content in entries.items():
                target_zip.writestr(name, content)

    try:
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def apply_template_master(pptx_path, template_path):
    template_prefixes = (
        "ppt/slideMasters/",
        "ppt/slideLayouts/",
        "ppt/theme/",
    )
    template_media = {"ppt/media/image1.jpeg"}
    temp_path = None
    try:
        with zipfile.ZipFile(pptx_path, "r") as source_zip, zipfile.ZipFile(template_path, "r") as template_zip:
            source_entries = {info.filename: source_zip.read(info.filename) for info in source_zip.infolist()}
            template_entries = {
                info.filename: template_zip.read(info.filename)
                for info in template_zip.infolist()
                if info.filename.startswith(template_prefixes) or info.filename in template_media
            }
            source_entries["[Content_Types].xml"] = _merge_template_content_types(
                source_entries["[Content_Types].xml"],
                template_zip.read("[Content_Types].xml"),
            )

        for name in list(source_entries):
            if name.startswith(template_prefixes):
                del source_entries[name]
            elif name.startswith("ppt/slides/_rels/") and name.endswith(".xml.rels"):
                source_entries[name] = _point_slides_to_template_layout(source_entries[name])
        source_entries.update(template_entries)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx", dir=pptx_path.parent) as tmp:
            temp_path = Path(tmp.name)
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for name, content in source_entries.items():
                target_zip.writestr(name, content)
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def keep_selected_slides(pptx_path, keep_slide_numbers):
    """按原始页序只保留指定页，页脚数字和各页内容保持不变。"""
    keep_set = set(keep_slide_numbers)
    ET.register_namespace("p", "http://schemas.openxmlformats.org/presentationml/2006/main")
    ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    presentation_part = "ppt/presentation.xml"
    slide_list_tag = "{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst"
    temp_path = None

    with zipfile.ZipFile(pptx_path, "r") as source:
        entries = {info.filename: source.read(info.filename) for info in source.infolist()}
        root = ET.fromstring(entries[presentation_part])
        slide_list = root.find(slide_list_tag)
        if slide_list is None:
            raise ValueError("PPT缺少幻灯片列表，无法按章节筛选")
        slide_nodes = list(slide_list)
        missing = [number for number in keep_slide_numbers if number < 1 or number > len(slide_nodes)]
        if missing:
            raise ValueError(f"章节页码超出当前PPT范围：{missing}，当前总页数 {len(slide_nodes)}")
        for index, node in enumerate(slide_nodes, start=1):
            if index not in keep_set:
                slide_list.remove(node)
        entries[presentation_part] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx", dir=pptx_path.parent) as tmp:
            temp_path = Path(tmp.name)
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            for name, content in entries.items():
                target.writestr(name, content)

    try:
        temp_path.replace(pptx_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="从数据库结果数据生成指定月份的月报 PPTX")
    parser.add_argument("--month", "--end-month", dest="end_month", required=True, type=month_argument, help="月报月份，格式 YYYY-MM")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--output", type=Path, help="输出PPTX；不传时根据 end-month 自动命名")
    parser.add_argument("--background-mode", choices=["ppt", "image"], default="ppt", help="底层模板来源：ppt（默认，使用模板PPT）或 image（图片背景）")
    parser.add_argument("--template", type=Path, help="模板PPT路径，默认使用 reporting/templates/通用模板.pptx；仅适用于 ppt 模式")
    parser.add_argument(
        "--section",
        choices=list(SECTION_SLIDE_MAP),
        help="可选：只生成指定章节，可选值：业务发展情况、专线自动情况、终端回收情况、业务支撑情况；不传则生成全部",
    )
    parser.add_argument("--keep-json", action="store_true", help="保留中间JSON数据")
    parser.add_argument('--manual-metrics-dir', type=Path, default=DEFAULT_DIRECTORY, help='标准化手工指标JSON目录，默认 outputs/manual_metrics')
    args = parser.parse_args()
    if args.background_mode == "image" and args.template:
        parser.error("--template 不能与 --background-mode image 同时使用")

    if args.end_month is not None:
        month_code = str(args.end_month)
        month_cn = f"{args.end_month.year}年{args.end_month.month}月"
        default_input = DATA_SOURCE_DIR / f"专线产品情况_{month_code}.xlsx"
        default_output = OUTPUT_DIR / f"互联网专线产品开通情况_{month_cn}.pptx"
    else:
        default_input = DEFAULT_INPUT
        default_output = DEFAULT_OUTPUT

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (args.output or default_output).resolve()
    template_path = (args.template or DEFAULT_TEMPLATE).resolve() if args.background_mode == "ppt" else None
    if not NODE_BIN.exists():
        raise FileNotFoundError(f"找不到Node运行时：{NODE_BIN}")
    if template_path is not None and not template_path.exists():
        raise FileNotFoundError(f"找不到PPT模板：{template_path}")

    required_manual = {
        '业务发展情况': set(), '终端回收情况': set(),
        '专线自动情况': {AUTOMATION}, '业务支撑情况': {WITHDRAWAL, QIKUAN, RETURN, REPEAT, COMBINED_REPEAT},
    }.get(args.section, METRIC_SETS)
    data = build_data(args.database, str(args.end_month), args.manual_metrics_dir if required_manual else None, required_manual)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_json = output_path.with_suffix(".json")
    data_json.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    output_path.with_suffix(".audit.json").write_text(json.dumps(data["dataAudit"], ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    env = os.environ.copy()
    env["NODE_PATH"] = str(NODE_MODULES)
    if template_path is not None:
        env["PPT_TEMPLATE_MASTER"] = "1"
    else:
        env.pop("PPT_TEMPLATE_MASTER", None)
    subprocess.run(
        [str(NODE_BIN), str(DRAW_SCRIPT), str(data_json), str(output_path)],
        cwd=BASE_DIR,
        env=env,
        check=True,
    )
    if template_path is not None:
        apply_template_master(output_path, template_path)
    color_city_product_data_labels(output_path)
    format_withdrawal_line_chart(output_path)
    format_complaint_fault_charts(output_path)
    replace_terminal_recovery_slides_from_template(output_path, data["terminalRecovery"], data["currentMonth"])
    if args.section:
        keep_selected_slides(output_path, SECTION_SLIDE_MAP[args.section])

    if not args.keep_json:
        data_json.unlink(missing_ok=True)
    print(f"完成：{output_path}")


if __name__ == "__main__":
    main()
