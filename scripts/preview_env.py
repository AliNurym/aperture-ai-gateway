"""Read the small set of local model settings needed by the preview launcher."""

from pathlib import Path

from dotenv import dotenv_values


INFERENCE_ENV_KEYS = (
    "GEMINI_API_KEY",
    "APERTURE_GEMINI_MODEL",
    "APERTURE_GEMINI_RATE_LAMPORTS_SEC",
)


def load_local_inference_environment(env_path: Path, environment) -> tuple[str, ...]:
    """Load preview inference settings without importing unrelated secrets.

    Existing process values take precedence. Only the Gemini key and its public
    model/tariff selectors are read from the local file; gateway and signer
    credentials are never copied into preview child environments.
    """
    env_path = Path(env_path)
    if not env_path.is_file():
        return ()

    values = dotenv_values(env_path)
    loaded = []
    for key in INFERENCE_ENV_KEYS:
        if key not in environment and values.get(key) is not None:
            environment[key] = values[key]
            loaded.append(key)
    return tuple(loaded)
