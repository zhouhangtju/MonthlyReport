"""地市终端回收页模板处理；独立于省级生成入口和省级页码。"""

import os
import posixpath
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

CITY_TERMINAL_SLIDES = (12, 13)
CITY_TERMINAL_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "终端回收页模版.pptx"


def _next_relationship_id(root):
    ids = []
    for rel in root:
        value = rel.attrib.get("Id", "")
        match = re.fullmatch(r"rId(\d+)", value)
        if match:
            ids.append(int(match.group(1)))
    return f"rId{max(ids, default=0) + 1}"


def _format_count(value) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _update_city_terminal_text(entries: dict, terminal_data: dict) -> None:
    """更新地市版终端回收文字，使用与模板替换一致的页码常量。"""
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

    slide12 = f"ppt/slides/slide{CITY_TERMINAL_SLIDES[0]}.xml"
    slide13 = f"ppt/slides/slide{CITY_TERMINAL_SLIDES[1]}.xml"
    if slide12 in entries:
        xml = entries[slide12].decode("utf-8")
        entries[slide12] = update_runs(
            xml,
            {"全省终端回收率": f"{target_city}终端回收率",
             f"{province_rate} ": f"{target_rate} "},
            {},
        ).encode("utf-8")
    if slide13 in entries:
        xml = entries[slide13].decode("utf-8")
        entries[slide13] = update_runs(
            xml,
            {province_completed: target_completed},
            {"全省终端": f"{target_city}终端"},
        ).encode("utf-8")


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
    month_text = str(datetime.strptime(display_month, "%Y-%m").month)
    city = terminal_data["city"]
    top = terminal_data["topInstaller"]
    top_devices = list(terminal_data["topDevices"])
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
        f"ppt/slides/slide{CITY_TERMINAL_SLIDES[0]}.xml": slide12_replacements,
        f"ppt/slides/slide{CITY_TERMINAL_SLIDES[1]}.xml": slide13_replacements,
    }.items():
        if slide_name in entries:
            entries[slide_name] = _replace_text_runs(
                entries[slide_name].decode("utf-8"),
                replacements,
            ).encode("utf-8")


def replace_city_terminal_recovery_slides_from_template(pptx_path, terminal_data, display_month, template_path=CITY_TERMINAL_TEMPLATE):
    """只替换地市版第12、13页，完整保留其余页面和页面顺序。"""
    pptx_path, template_path = Path(pptx_path), Path(template_path)
    if not template_path.exists():
        raise FileNotFoundError(f"找不到地市终端回收模板：{template_path}")
    temp_path = None
    seed_mapping = {
        "ppt/slides/slide2.xml": f"ppt/slides/slide{CITY_TERMINAL_SLIDES[0]}.xml",
        "ppt/slides/slide3.xml": f"ppt/slides/slide{CITY_TERMINAL_SLIDES[1]}.xml",
    }
    with zipfile.ZipFile(pptx_path, "r") as source_zip, zipfile.ZipFile(template_path, "r") as template_zip:
        entries = {info.filename: source_zip.read(info.filename) for info in source_zip.infolist()}
        missing = set(seed_mapping.values()) - set(entries)
        if missing:
            raise ValueError(f"地市终端回收目标页面不存在：{sorted(missing)}")
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
        _update_city_terminal_text(entries, terminal_data)

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
