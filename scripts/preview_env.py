"""Read the small set of local model settings needed by the preview launcher."""

from pathlib import Path

from dotenv import dotenv_values


PREVIEW_ENV_KEYS = (
    "GEMINI_API_KEY",
    "APERTURE_GEMINI_MODEL",
    "DEEPSEEK_API_KEY",
    "APERTURE_DEEPSEEK_MODEL",
    "APERTURE_WORKER_RATE_LAMPORTS_SEC",
)


def load_local_inference_environment(env_path: Path, environment) -> tuple[str, ...]:
    """Load preview inference settings without importing unrelated secrets.

    Existing process values take precedence. Only the supported model keys and public
    model selectors and the optional preview worker rate are read from the local file; gateway and signer
    credentials are never copied into preview child environments.
    """
    env_path = Path(env_path)
    if not env_path.is_file():
        return ()

    values = dotenv_values(env_path)
    loaded = []
    for key in PREVIEW_ENV_KEYS:
        if key not in environment and values.get(key) is not None:
            environment[key] = values[key]
            loaded.append(key)
    return tuple(loaded)
