import os
from pathlib import Path

from dotenv import load_dotenv


def load_openai_api_key():
    env_path = find_env_file()
    if env_path is not None:
        load_dotenv(dotenv_path=env_path)

    return os.getenv("OPENAI_API_KEY")


def find_env_file():
    current_file = Path(__file__).resolve()
    candidates = [
        current_file.parent / ".env",
        Path.cwd() / ".env",
    ]

    try:
        from ament_index_python.packages import get_package_share_directory

        candidates.append(Path(get_package_share_directory("voice_processing")) / ".env")
    except Exception:
        pass

    for parent in current_file.parents:
        candidates.append(parent / "voice_processing" / ".env")

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None
