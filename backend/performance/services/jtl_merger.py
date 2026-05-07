"""多 jtl 流式 N-way merge by timeStamp（v1.2 多机调度后合并 agent 各自的 jtl）。

JMeter JTL CSV 第一列固定是 `timeStamp`（毫秒）。多文件 heap-merge：
  - 每个 input 起一个 csv reader
  - 第一个文件的 header 写到输出，其余 skip header
  - heap 按 timeStamp 排序，每次 pop 最小的写出来 + push 该文件下一行
  - 文件读完自动从 heap 移除

避免全量 OOM：单点常驻内存只是 N 个 reader + N 行 buffer，O(N) 而不是 O(jtl 总行数)。
"""
from __future__ import annotations

import csv
import heapq
from pathlib import Path
from typing import Iterator


def _row_iter(path: Path, encoding: str = 'utf-8') -> tuple[list[str], Iterator[list[str]]]:
    """打开文件，返回 (header, 数据行生成器)。"""
    f = path.open('r', encoding=encoding, newline='')
    reader = csv.reader(f)
    try:
        header = next(reader)
    except StopIteration:
        f.close()
        return [], iter(())

    def gen():
        try:
            for row in reader:
                yield row
        finally:
            f.close()
    return header, gen()


def merge_jtls(input_paths: list[Path], output_path: Path,
               *, encoding: str = 'utf-8') -> int:
    """
    把多个 jtl 按第 0 列（timeStamp）merge sort 写到 output_path。
    返回写出的数据行数（不含 header）。

    边界：
    - 输入文件 header 必须一致（JMeter 同版本 + 同 -J 配置即一致）
    - 第 0 列非 int/float 的行（脏数据）按 0 排序，不抛错
    """
    if not input_paths:
        output_path.write_text('')
        return 0

    iters: list[tuple[list[str], Iterator[list[str]]]] = []
    common_header: list[str] | None = None
    for p in input_paths:
        header, gen = _row_iter(Path(p), encoding=encoding)
        if not header:
            continue
        if common_header is None:
            common_header = header
        iters.append((header, gen))

    if not iters or common_header is None:
        output_path.write_text('')
        return 0

    def _ts(row: list[str]) -> int:
        try:
            return int(row[0])
        except (IndexError, ValueError):
            return 0

    # heap 元素：(timestamp, source_index, row)
    # source_index 让相同 timestamp 也能稳定排序，且避免 Python 对 list 比较出错
    heap: list[tuple[int, int, list[str]]] = []
    for src_idx, (_h, gen) in enumerate(iters):
        try:
            row = next(gen)
            heapq.heappush(heap, (_ts(row), src_idx, row))
        except StopIteration:
            pass

    written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding=encoding, newline='') as out:
        writer = csv.writer(out)
        writer.writerow(common_header)
        while heap:
            ts, src_idx, row = heapq.heappop(heap)
            writer.writerow(row)
            written += 1
            try:
                nxt = next(iters[src_idx][1])
                heapq.heappush(heap, (_ts(nxt), src_idx, nxt))
            except StopIteration:
                pass
    return written
