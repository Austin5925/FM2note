from __future__ import annotations

from src.config import AppConfig
from src.transcriber.base import Transcriber, TranscriptionError


def create_transcriber(config: AppConfig) -> Transcriber:
    """根据配置创建对应的转写器实例。

    Args:
        config: 应用配置

    Returns:
        Transcriber 实例

    Raises:
        TranscriptionError: 不支持的引擎或缺少必要配置
    """
    engine = config.asr_engine

    if engine == "tingwu":
        if not config.dashscope_api_key:
            raise TranscriptionError("通义听悟需要配置 DASHSCOPE_API_KEY")
        if not config.tingwu_app_id:
            raise TranscriptionError("通义听悟需要配置 TINGWU_APP_ID")

        from src.transcriber.tingwu import TingwuTranscriber

        return TingwuTranscriber(
            api_key=config.dashscope_api_key,
            app_id=config.tingwu_app_id,
        )

    elif engine == "funasr":
        if not config.dashscope_api_key:
            raise TranscriptionError("FunASR 需要配置 DASHSCOPE_API_KEY")

        from src.transcriber.funasr import FunASRTranscriber

        return FunASRTranscriber(api_key=config.dashscope_api_key)

    elif engine == "paraformer":
        if not config.dashscope_api_key:
            raise TranscriptionError("Paraformer 需要配置 DASHSCOPE_API_KEY")

        from src.transcriber.funasr import ParaformerTranscriber

        return ParaformerTranscriber(api_key=config.dashscope_api_key)

    elif engine == "bailian":
        if not config.dashscope_api_key:
            raise TranscriptionError("百炼 ASR 需要配置 DASHSCOPE_API_KEY")

        from src.transcriber.bailian import BailianTranscriber

        return BailianTranscriber(api_key=config.dashscope_api_key)

    elif engine == "whisper_api":
        if not config.openai_api_key:
            raise TranscriptionError("Whisper API 需要配置 OPENAI_API_KEY")

        from src.transcriber.whisper_api import WhisperTranscriber

        return WhisperTranscriber(
            api_key=config.openai_api_key,
            temp_dir=config.temp_dir,
        )

    else:
        raise TranscriptionError(f"不支持的 ASR 引擎: {engine}")
