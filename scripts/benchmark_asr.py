"""ASR 引擎对比评测脚本

用法：
    python scripts/benchmark_asr.py --samples samples.yaml

samples.yaml 格式：
    samples:
      - name: "样本1"
        audio_url: "https://..."
      - name: "样本2"
        audio_url: "https://..."
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import click
import yaml
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import AppConfig, load_config
from src.transcriber.base import TranscriptionError
from src.transcriber.factory import create_transcriber


@dataclass
class BenchmarkResult:
    engine: str
    sample_name: str
    duration_seconds: float
    char_count: int
    text_preview: str
    error: str | None = None


async def run_single(engine_name: str, config: AppConfig, audio_url: str, sample_name: str) -> BenchmarkResult:
    """运行单个引擎对单个样本的评测"""
    original_engine = config.asr_engine
    config.asr_engine = engine_name

    try:
        transcriber = create_transcriber(config)
    except TranscriptionError as e:
        return BenchmarkResult(
            engine=engine_name,
            sample_name=sample_name,
            duration_seconds=0,
            char_count=0,
            text_preview="",
            error=f"初始化失败: {e}",
        )
    finally:
        config.asr_engine = original_engine

    start = time.time()
    try:
        result = await transcriber.transcribe(audio_url)
        elapsed = time.time() - start
        return BenchmarkResult(
            engine=engine_name,
            sample_name=sample_name,
            duration_seconds=elapsed,
            char_count=len(result.text),
            text_preview=result.text[:200],
        )
    except Exception as e:
        elapsed = time.time() - start
        return BenchmarkResult(
            engine=engine_name,
            sample_name=sample_name,
            duration_seconds=elapsed,
            char_count=0,
            text_preview="",
            error=str(e),
        )


async def run_benchmark(samples: list[dict], engines: list[str], config: AppConfig) -> list[BenchmarkResult]:
    """对所有样本运行所有引擎评测"""
    results = []
    for sample in samples:
        for engine in engines:
            logger.info("评测: {} × {}", engine, sample["name"])
            result = await run_single(engine, config, sample["audio_url"], sample["name"])
            results.append(result)
            if result.error:
                logger.error("  失败: {}", result.error)
            else:
                logger.success(
                    "  完成: {:.1f}s, {} 字",
                    result.duration_seconds,
                    result.char_count,
                )
    return results


def generate_report(results: list[BenchmarkResult]) -> str:
    """生成 Markdown 格式的对比报告"""
    lines = [
        "# ASR 引擎对比评测报告\n",
        f"评测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "## 总览\n",
        "| 引擎 | 样本 | 耗时(秒) | 字数 | 状态 |",
        "|------|------|----------|------|------|",
    ]

    for r in results:
        status = "失败" if r.error else "成功"
        lines.append(
            f"| {r.engine} | {r.sample_name} | {r.duration_seconds:.1f} | {r.char_count} | {status} |"
        )

    lines.append("\n## 转写文本预览\n")
    for r in results:
        lines.append(f"### {r.engine} — {r.sample_name}\n")
        if r.error:
            lines.append(f"**错误**: {r.error}\n")
        else:
            lines.append(f"```\n{r.text_preview}...\n```\n")

    return "\n".join(lines)


@click.command()
@click.option("--samples", required=True, help="音频样本 YAML 文件路径")
@click.option("--config-path", default="config/config.yaml", help="配置文件路径")
@click.option(
    "--engines",
    default="tingwu,bailian,whisper_api",
    help="要测试的引擎列表（逗号分隔）",
)
@click.option("--output", default="data/benchmark_report.md", help="报告输出路径")
def main(samples: str, config_path: str, engines: str, output: str):
    """运行 ASR 引擎对比评测"""
    config = load_config(config_path)

    with open(samples, encoding="utf-8") as f:
        sample_data = yaml.safe_load(f)

    engine_list = [e.strip() for e in engines.split(",")]
    sample_list = sample_data.get("samples", [])

    if not sample_list:
        logger.error("未找到音频样本")
        return

    logger.info("开始评测: {} 个引擎 × {} 个样本", len(engine_list), len(sample_list))

    results = asyncio.run(run_benchmark(sample_list, engine_list, config))
    report = generate_report(results)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    logger.success("报告已生成: {}", output_path)
    print(report)


if __name__ == "__main__":
    main()
