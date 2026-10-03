"""Resident bilingual Piper voices; serialize inference to respect CPU quota."""

import json
import threading
import wave

from . import runtime

_models = {}
_inference_lock = threading.Lock()


def load_voice(voice):
    if voice not in _models:
        import onnxruntime
        from piper import PiperVoice
        from piper.config import PiperConfig

        # Docker CPU quota is smaller than the visible host CPU count. Explicit
        # limits prevent ONNX from starting a large pool and starving RTP.
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = runtime.piper_threads
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = runtime.piper_cpu_mem_arena
        model_path = runtime.piper_voices[voice]["path"]
        with open(model_path + ".json", encoding="utf-8") as source:
            config = PiperConfig.from_dict(json.load(source))
        _models[voice] = PiperVoice(
            config=config,
            session=onnxruntime.InferenceSession(
                model_path,
                sess_options=options,
                providers=["CPUExecutionProvider"],
            ),
        )


def synthesize_neural(text: str, voice: str, destination: str):
    from piper import SynthesisConfig

    # A single resident model avoids a cold model load for every reply.
    with _inference_lock:
        load_voice(voice)
        with wave.open(destination, "wb") as output:
            _models[voice].synthesize_wav(
                text,
                output,
                syn_config=SynthesisConfig(
                    length_scale=runtime.piper_voices[voice]["length_scale"]
                ),
            )
