"""Phase 3 — Parse Roslyn XML doc files into one chunk per documented member.

Roslyn emits flat <member> entries keyed by an ID string:
  T:Namespace.Class          (type)
  M:Namespace.Class.Method(ParamType,...)   (method/ctor)
  P:Namespace.Class.Prop     (property)
  F:Namespace.Class.Field    (field)
  E:Namespace.Class.Event    (event)

We iterate every <member>, group by declaring class, and emit one chunk per
member containing:
  - fully-qualified class name
  - class summary (from the T: entry of that class, if present)
  - member name + reconstructed signature
  - member <summary> (and <returns>, <remarks> when present — these are part of
    the documented behaviour the spec implicitly covers as the member's docs)
  - <param> names + descriptions

MAX_CHARS is a defensive guard only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from lxml import etree

MAX_CHARS = 8000  # defensive only


@dataclass
class Chunk:
    chunk_id: str          # stable id: assembly + member_id
    assembly: str          # source XML file (Algorithm / Common / Indicators / ...)
    member_kind: str       # T, M, P, F, E
    member_id: str         # raw Roslyn id (without prefix), e.g. QuantConnect.Foo.Bar(Int32)
    class_fqn: str         # fully qualified class name
    member_name: str       # short name (e.g. SetHoldings)
    signature: str         # reconstructed signature, e.g. SetHoldings(QuantConnect.Symbol, System.Decimal)
    text: str              # composed chunk text fed to the embedder


# ----- ID parsing ------------------------------------------------------------

def split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` at depth 0 (respect nested generic { } or angle parens)."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in s:
        if ch in "{<(":
            depth += 1
            cur.append(ch)
        elif ch in "}>)":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    return out


def parse_member_id(raw: str) -> tuple[str, str, str, str, str]:
    """Parse a Roslyn member id like 'M:NS.Class.Method(A,B)'.

    Returns (kind, class_fqn, member_name, signature, body_no_kind).

    For T: entries, class_fqn == body_no_kind and member_name == class_fqn.
    """
    kind, body = raw[0], raw[2:]  # 'M', ':' stripped
    if kind == "T":
        class_fqn = body
        member_name = body.rsplit(".", 1)[-1]
        return kind, class_fqn, member_name, class_fqn, body

    # split off param list if present
    paren = body.find("(")
    head = body if paren < 0 else body[:paren]
    params_str = "" if paren < 0 else body[paren:]

    # head: NS...Class.MemberName  — last dot separates class from member
    # Generic methods have backtick syntax: Method``1 — keep as-is in member name
    last_dot = head.rfind(".")
    class_fqn = head[:last_dot]
    member_name = head[last_dot + 1:]
    signature = f"{member_name}{params_str}"
    return kind, class_fqn, member_name, signature, body


# ----- text extraction --------------------------------------------------------

def el_text(el) -> str:
    """Flatten an XML element to plain text, preserving <see cref> targets and
    collapsing whitespace."""
    if el is None:
        return ""
    parts: list[str] = []

    def walk(node):
        if node.text:
            parts.append(node.text)
        for child in node:
            tag = etree.QName(child).localname
            if tag == "see" or tag == "seealso":
                ref = child.get("cref") or child.get("href") or child.get("langword")
                if ref:
                    # strip leading kind: e.g. "T:" "M:"
                    if len(ref) > 2 and ref[1] == ":":
                        ref = ref[2:]
                    parts.append(ref)
            elif tag == "paramref" or tag == "typeparamref":
                name = child.get("name")
                if name:
                    parts.append(name)
            else:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    text = "".join(parts)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ----- main parse -------------------------------------------------------------

def parse_xml_file(xml_path: Path) -> tuple[str, list[etree._Element]]:
    tree = etree.parse(str(xml_path))
    root = tree.getroot()
    assembly_el = root.find("assembly/name")
    assembly = assembly_el.text if assembly_el is not None else xml_path.stem
    members = list(root.findall("members/member"))
    return assembly, members


def build_chunks_from_xml(xml_paths: Iterable[Path]) -> list[Chunk]:
    """Build chunks across many XML files. Class summary is resolved per file."""
    chunks: list[Chunk] = []
    for xml_path in xml_paths:
        assembly, members = parse_xml_file(xml_path)

        # First pass: collect class (T:) summaries within this file
        class_summary: dict[str, str] = {}
        for m in members:
            name_attr = m.get("name", "")
            if not name_attr or name_attr[1] != ":":
                continue
            if name_attr[0] != "T":
                continue
            _, class_fqn, _, _, _ = parse_member_id(name_attr)
            summary = el_text(m.find("summary"))
            class_summary[class_fqn] = summary

        # Second pass: emit one chunk per member
        for m in members:
            name_attr = m.get("name", "")
            if not name_attr or len(name_attr) < 3 or name_attr[1] != ":":
                continue
            kind = name_attr[0]
            if kind not in ("T", "M", "P", "F", "E"):
                continue
            _, class_fqn, member_name, signature, body = parse_member_id(name_attr)

            summary = el_text(m.find("summary"))
            returns = el_text(m.find("returns"))
            remarks = el_text(m.find("remarks"))

            params: list[tuple[str, str]] = []
            for p in m.findall("param"):
                pname = p.get("name") or ""
                pdesc = el_text(p)
                params.append((pname, pdesc))

            type_params: list[tuple[str, str]] = []
            for tp in m.findall("typeparam"):
                tpname = tp.get("name") or ""
                tpdesc = el_text(tp)
                type_params.append((tpname, tpdesc))

            # Compose chunk text per spec
            lines: list[str] = []
            lines.append(f"Class: {class_fqn}")
            cs = class_summary.get(class_fqn, "")
            if cs:
                lines.append(f"Class summary: {cs}")
            if kind == "T":
                lines.append(f"Type: {class_fqn}")
            else:
                lines.append(f"Member: {member_name}")
                lines.append(f"Signature: {signature}")
            if summary:
                lines.append(f"Summary: {summary}")
            if returns:
                lines.append(f"Returns: {returns}")
            if remarks:
                lines.append(f"Remarks: {remarks}")
            for pname, pdesc in params:
                lines.append(f"Param {pname}: {pdesc}")
            for tpname, tpdesc in type_params:
                lines.append(f"TypeParam {tpname}: {tpdesc}")
            text = "\n".join(lines)
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS]

            chunk_id = f"{assembly}::{name_attr}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    assembly=assembly,
                    member_kind=kind,
                    member_id=body,
                    class_fqn=class_fqn,
                    member_name=member_name,
                    signature=signature,
                    text=text,
                )
            )
    return chunks


def write_chunks_jsonl(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


def discover_xml_files(lean_src: Path) -> list[Path]:
    """The canonical <DocumentationFile> output for each source project that
    emits one.

    Each csproj that declares <DocumentationFile> produces one XML file. That
    file is then copied into every downstream project's bin/Release as a
    build artifact. Globbing bin/Release would yield ~14x duplicates, so we
    enumerate by csproj instead and resolve each to its own bin/Release.

    Test projects are excluded.
    """
    from lxml import etree as _et

    paths: list[Path] = []
    for csproj in lean_src.glob("*/*.csproj"):
        # Skip test projects
        if "Tests" in csproj.parts or csproj.parent.name == "Tests":
            continue
        try:
            tree = _et.parse(str(csproj))
        except Exception:
            continue
        root = tree.getroot()
        # csproj is xmlns-free SDK style; use localname strip
        doc_file_el = None
        for el in root.iter():
            if _et.QName(el).localname == "DocumentationFile":
                doc_file_el = el
                break
        if doc_file_el is None or not doc_file_el.text:
            continue
        # Expand $(Configuration) — we built Release
        rel = doc_file_el.text.replace("$(Configuration)", "Release")
        rel = rel.replace("\\", "/")
        xml_path = (csproj.parent / rel).resolve()
        if xml_path.exists():
            paths.append(xml_path)
    return sorted(set(paths))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--lean-src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    lean_src = args.lean_src.resolve()
    xmls = discover_xml_files(lean_src)
    print(f"Found {len(xmls)} XML doc files:")
    for x in xmls:
        print(f"  {x.relative_to(lean_src)}")

    chunks = build_chunks_from_xml(xmls)
    print(f"Built {len(chunks)} chunks")
    write_chunks_jsonl(chunks, args.out)
    print(f"Wrote {args.out}")
